"""使用记录业务规则：自动计算使用时长与进尺，并在同一事务内维护设备累计值。"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError, ErrorCode
from app.models.equipment import Equipment
from app.models.operation import WellOperation
from app.models.user import User
from app.schemas.well_operation import WellOperationCreate, WellOperationUpdate

ZERO = Decimal("0")
TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _compute_derived(data: dict) -> dict:
    """补齐使用时长与进尺：能算则算，手工填写的值优先（编写报告 4.3）。"""
    start, end = data.get("start_date"), data.get("end_date")
    if data.get("run_hours") is None and start and end and end >= start:
        seconds = Decimal(str((end - start).total_seconds()))
        data["run_hours"] = _round(seconds / Decimal(3600))

    in_depth, out_depth = data.get("run_in_depth"), data.get("run_out_depth")
    if data.get("footage") is None and in_depth is not None and out_depth is not None:
        data["footage"] = _round(Decimal(out_depth) - Decimal(in_depth))
    return data


def _apply_totals(equipment: Equipment, hours: Decimal | None, count_delta: int) -> None:
    """把使用时长与次数增减到设备台账上，调用方保证与使用记录同事务。"""
    equipment.total_run_hours = _round((equipment.total_run_hours or ZERO) + (hours or ZERO))
    equipment.total_run_count = max(0, (equipment.total_run_count or 0) + count_delta)


def list_operations(
    db: Session,
    equipment_id: int | None = None,
    well_no: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WellOperation], int]:
    stmt = select(WellOperation)
    if equipment_id is not None:
        stmt = stmt.where(WellOperation.equipment_id == equipment_id)
    if well_no:
        stmt = stmt.where(WellOperation.well_no.like(f"%{well_no.strip()}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.execute(
            stmt.order_by(WellOperation.start_date.desc(), WellOperation.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        .unique()
        .scalars()
    )
    return items, total


def get_operation(db: Session, operation_id: int) -> WellOperation:
    operation = db.get(WellOperation, operation_id)
    if operation is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "使用记录不存在", 404)
    return operation


def _require_equipment(db: Session, equipment_id: int) -> Equipment:
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "关联设备不存在", 404)
    return equipment


def create_operation(db: Session, payload: WellOperationCreate, user: User) -> WellOperation:
    equipment = _require_equipment(db, payload.equipment_id)

    data = _compute_derived(payload.model_dump())
    operation = WellOperation(**data, created_by=user.id, updated_by=user.id)
    db.add(operation)
    db.flush()

    _apply_totals(equipment, operation.run_hours, 1)
    return operation


def update_operation(
    db: Session, operation_id: int, payload: WellOperationUpdate, user: User
) -> WellOperation:
    operation = get_operation(db, operation_id)
    equipment = db.get(Equipment, operation.equipment_id)
    previous_hours = operation.run_hours or ZERO

    provided = payload.model_dump(exclude_unset=True)

    # 只在计算所需的输入发生变化时重算，且算得出值才覆盖，避免抹掉手工填写的数字
    recompute_hours = "run_hours" not in provided and bool({"start_date", "end_date"} & provided.keys())
    recompute_footage = "footage" not in provided and bool(
        {"run_in_depth", "run_out_depth"} & provided.keys()
    )

    effective = {
        "start_date": operation.start_date,
        "end_date": operation.end_date,
        "run_hours": operation.run_hours,
        "run_in_depth": operation.run_in_depth,
        "run_out_depth": operation.run_out_depth,
        "footage": operation.footage,
        **provided,
    }
    if recompute_hours:
        effective["run_hours"] = None
    if recompute_footage:
        effective["footage"] = None
    effective = _compute_derived(effective)

    updates = dict(provided)
    if recompute_hours and effective["run_hours"] is not None:
        updates["run_hours"] = effective["run_hours"]
    if recompute_footage and effective["footage"] is not None:
        updates["footage"] = effective["footage"]

    for field, value in updates.items():
        setattr(operation, field, value)
    operation.updated_by = user.id
    db.flush()

    if equipment is not None:
        delta = (operation.run_hours or ZERO) - previous_hours
        if delta:
            _apply_totals(equipment, delta, 0)
    return operation


def delete_operation(db: Session, operation_id: int, user: User) -> None:
    operation = get_operation(db, operation_id)
    equipment = db.get(Equipment, operation.equipment_id)
    if equipment is not None:
        _apply_totals(equipment, -(operation.run_hours or ZERO), -1)
    db.delete(operation)
