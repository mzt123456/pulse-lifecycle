"""设备台账业务规则：编号唯一、乐观锁、状态流水与删除保护。"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError, ErrorCode
from app.core.timeutil import local_now
from app.models.equipment import Equipment, EquipmentStatusLog
from app.models.operation import WellOperation
from app.models.user import User
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate


def list_equipment(
    db: Session,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Equipment], int]:
    stmt = select(Equipment)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Equipment.equipment_no.like(pattern), Equipment.model.like(pattern)))
    if status:
        stmt = stmt.where(Equipment.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.execute(
            stmt.order_by(Equipment.equipment_no).limit(page_size).offset((page - 1) * page_size)
        ).scalars()
    )
    return items, total


def get_equipment(db: Session, equipment_id: int) -> Equipment:
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "设备不存在", 404)
    return equipment


def _ensure_no_unique(db: Session, equipment_no: str, exclude_id: int | None = None) -> None:
    stmt = select(Equipment.id).where(Equipment.equipment_no == equipment_no)
    if exclude_id is not None:
        stmt = stmt.where(Equipment.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise BusinessError(ErrorCode.CONFLICT, f"脉冲编号 {equipment_no} 已存在", 409)


def create_equipment(db: Session, payload: EquipmentCreate, user: User) -> Equipment:
    _ensure_no_unique(db, payload.equipment_no)

    equipment = Equipment(**payload.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(equipment)
    db.flush()
    db.add(
        EquipmentStatusLog(
            equipment_id=equipment.id,
            from_status=None,
            to_status=equipment.status,
            reason="新建设备",
            changed_by=user.id,
            changed_at=local_now(),
        )
    )
    return equipment


def update_equipment(
    db: Session, equipment_id: int, payload: EquipmentUpdate, user: User
) -> Equipment:
    equipment = get_equipment(db, equipment_id)
    if payload.version != equipment.version:
        raise BusinessError(ErrorCode.CONFLICT, "设备已被他人修改，请刷新后重试", 409)

    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    new_no = data.get("equipment_no")
    if new_no and new_no != equipment.equipment_no:
        _ensure_no_unique(db, new_no, exclude_id=equipment.id)

    previous_status = equipment.status
    for field, value in data.items():
        setattr(equipment, field, value)
    equipment.version = payload.version + 1
    equipment.updated_by = user.id

    if data.get("status") and equipment.status != previous_status:
        db.add(
            EquipmentStatusLog(
                equipment_id=equipment.id,
                from_status=previous_status,
                to_status=equipment.status,
                reason="编辑变更状态",
                changed_by=user.id,
                changed_at=local_now(),
            )
        )
    return equipment


def delete_equipment(db: Session, equipment_id: int, user: User) -> None:
    equipment = get_equipment(db, equipment_id)

    usage_count = (
        db.scalar(
            select(func.count())
            .select_from(WellOperation)
            .where(WellOperation.equipment_id == equipment.id)
        )
        or 0
    )
    if usage_count:
        raise BusinessError(
            ErrorCode.CONFLICT,
            f"该设备已有 {usage_count} 条使用记录，请先处理这些记录再删除",
            409,
        )
    db.delete(equipment)
