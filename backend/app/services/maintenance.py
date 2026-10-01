"""维保工单业务规则：步骤清单生成、工单号生成与完成状态维护。"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import BusinessError, ErrorCode
from app.core.timeutil import local_now
from app.models.equipment import Equipment
from app.models.maintenance import MaintenanceOrder, MaintenanceStep
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceOrderCreate,
    MaintenanceOrderUpdate,
    StepCompleteRequest,
)

# 四级维保步骤清单：每级在一级基础上累加（编写报告 8.2）。
# 注：这是按报告文字整理的版本，拿到单机版的步骤表后再逐条核对。
LEVEL_1 = ["外观检查", "油位测量", "密封性检查", "连接紧固", "功能测试"]
LEVEL_2_EXTRA = ["油液更换", "转子拆卸检查", "定子检查", "轴承检查", "阀总成检查"]
LEVEL_3_EXTRA = ["电机性能测试", "驱动器检测", "全面探伤", "密封件更换", "整机装配调试", "出厂测试"]
LEVEL_4_EXTRA = [
    "整机拆卸",
    "零部件探伤",
    "电气系统全面检测",
    "密封件与轴承传动件更换",
    "整机装配",
    "性能测试",
    "出厂验收",
]

STEP_TEMPLATES: dict[str, list[str]] = {
    "一级维保": list(LEVEL_1),
    "二级维保": LEVEL_1 + LEVEL_2_EXTRA,
    "三级维保": LEVEL_1 + LEVEL_2_EXTRA + LEVEL_3_EXTRA,
    "四级维保": LEVEL_1 + LEVEL_2_EXTRA + LEVEL_3_EXTRA + LEVEL_4_EXTRA,
}

STATUS_IN_PROGRESS = "进行中"
STATUS_DONE = "已完成"


def _require_level(level: str) -> list[str]:
    template = STEP_TEMPLATES.get(level)
    if template is None:
        raise BusinessError(
            ErrorCode.BUSINESS_RULE,
            f"维保等级不正确：{level}，可选值为 {'、'.join(STEP_TEMPLATES)}",
            422,
        )
    return template


def _build_steps(order: MaintenanceOrder, level: str) -> None:
    """把步骤挂到工单的关系集合上，保证内存中的清单与数据库一致。"""
    for index, name in enumerate(_require_level(level), start=1):
        order.steps.append(MaintenanceStep(seq=index, name=name, is_done=False))


def _generate_order_no(db: Session, prefix: str) -> str:
    """按“前缀 + 年月日 + 三位序号”生成，序号取当天最大值加一。"""
    today = local_now().strftime("%Y%m%d")
    pattern = f"{prefix}{today}%"
    latest = db.scalar(
        select(func.max(MaintenanceOrder.order_no)).where(MaintenanceOrder.order_no.like(pattern))
    )
    sequence = 1 if latest is None else int(latest[len(prefix) + 8 :]) + 1
    return f"{prefix}{today}{sequence:03d}"


def list_orders(
    db: Session,
    equipment_id: int | None = None,
    level: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MaintenanceOrder], int]:
    stmt = select(MaintenanceOrder)
    if equipment_id is not None:
        stmt = stmt.where(MaintenanceOrder.equipment_id == equipment_id)
    if level:
        stmt = stmt.where(MaintenanceOrder.level == level)
    if status:
        stmt = stmt.where(MaintenanceOrder.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.execute(
            stmt.order_by(MaintenanceOrder.id.desc()).limit(page_size).offset((page - 1) * page_size)
        )
        .unique()
        .scalars()
    )
    return items, total


def get_order(db: Session, order_id: int) -> MaintenanceOrder:
    order = db.get(MaintenanceOrder, order_id)
    if order is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "维保工单不存在", 404)
    return order


def create_order(
    db: Session, payload: MaintenanceOrderCreate, user: User, settings: Settings | None = None
) -> MaintenanceOrder:
    settings = settings or get_settings()
    _require_level(payload.level)

    equipment = db.get(Equipment, payload.equipment_id)
    if equipment is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "关联设备不存在", 404)

    data = payload.model_dump()
    if data.get("start_date") is None:
        data["start_date"] = local_now().date()

    order: MaintenanceOrder | None = None
    for _ in range(5):
        # 唯一索引兜底：并发下工单号冲突时换号重试（编写报告 4.4）
        order_no = _generate_order_no(db, settings.maintenance_order_prefix)
        try:
            with db.begin_nested():
                order = MaintenanceOrder(
                    **data,
                    order_no=order_no,
                    status=STATUS_IN_PROGRESS,
                    created_by=user.id,
                    updated_by=user.id,
                )
                db.add(order)
                db.flush()
                _build_steps(order, payload.level)
                db.flush()
        except IntegrityError:
            order = None
            continue
        break

    if order is None:
        raise BusinessError(ErrorCode.CONFLICT, "工单号生成冲突，请稍后重试", 409)
    return order


def update_order(
    db: Session, order_id: int, payload: MaintenanceOrderUpdate, user: User
) -> MaintenanceOrder:
    order = get_order(db, order_id)
    data = payload.model_dump(exclude_unset=True)

    new_level = data.pop("level", None)
    if new_level is not None and new_level != order.level:
        _require_level(new_level)
        order.steps.clear()  # 等级变化时重建步骤清单
        db.flush()
        order.level = new_level
        _build_steps(order, new_level)
        db.flush()

    previous_status = order.status
    for field, value in data.items():
        setattr(order, field, value)
    order.updated_by = user.id

    if order.status == STATUS_DONE and previous_status != STATUS_DONE:
        if order.end_date is None:
            order.end_date = local_now().date()
        # 完成后刷新设备的最近维保时间，供维保提醒使用
        equipment = db.get(Equipment, order.equipment_id)
        if equipment is not None:
            equipment.last_maintenance_at = local_now()
    db.flush()
    return order


def complete_step(
    db: Session, order_id: int, step_id: int, payload: StepCompleteRequest, user: User
) -> MaintenanceStep:
    order = get_order(db, order_id)
    step = db.get(MaintenanceStep, step_id)
    if step is None or step.order_id != order.id:
        raise BusinessError(ErrorCode.NOT_FOUND, "该工单下没有这个步骤", 404)

    step.is_done = payload.is_done
    step.remark = payload.remark if payload.remark is not None else step.remark
    if payload.is_done:
        step.done_by = user.id
        step.done_at = local_now()
    else:
        step.done_by = None
        step.done_at = None
    db.flush()
    # done_by_user 是只读关系，改了 done_by 之后需要让它重新加载，否则返回的姓名是旧值
    db.expire(step, ["done_by_user"])
    return step
