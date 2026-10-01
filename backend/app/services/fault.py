"""故障记录业务规则。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError, ErrorCode
from app.models.equipment import Equipment
from app.models.fault import FaultRecord
from app.models.user import User
from app.schemas.fault import FaultRecordCreate, FaultRecordUpdate
from app.services import dict as dict_service

FAULT_TYPE_CATEGORY = "故障类型"
FAULT_STATUS_CATEGORY = "故障处理状态"


def list_faults(
    db: Session,
    equipment_id: int | None = None,
    fault_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[FaultRecord], int]:
    stmt = select(FaultRecord)
    if equipment_id is not None:
        stmt = stmt.where(FaultRecord.equipment_id == equipment_id)
    if fault_type:
        stmt = stmt.where(FaultRecord.fault_type == fault_type)
    if status:
        stmt = stmt.where(FaultRecord.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.execute(
            stmt.order_by(FaultRecord.occurred_at.desc(), FaultRecord.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        .unique()
        .scalars()
    )
    return items, total


def get_fault(db: Session, fault_id: int) -> FaultRecord:
    record = db.get(FaultRecord, fault_id)
    if record is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "故障记录不存在", 404)
    return record


def create_fault(db: Session, payload: FaultRecordCreate, user: User) -> FaultRecord:
    if db.get(Equipment, payload.equipment_id) is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "关联设备不存在", 404)

    dict_service.ensure_value(db, FAULT_TYPE_CATEGORY, payload.fault_type, "故障类型")
    dict_service.ensure_value(db, FAULT_STATUS_CATEGORY, payload.status, "处理状态")

    record = FaultRecord(**payload.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(record)
    db.flush()
    return record


def update_fault(
    db: Session, fault_id: int, payload: FaultRecordUpdate, user: User
) -> FaultRecord:
    record = get_fault(db, fault_id)
    data = payload.model_dump(exclude_unset=True)

    dict_service.ensure_value(db, FAULT_TYPE_CATEGORY, data.get("fault_type"), "故障类型")
    dict_service.ensure_value(db, FAULT_STATUS_CATEGORY, data.get("status"), "处理状态")

    for field, value in data.items():
        setattr(record, field, value)
    record.updated_by = user.id
    db.flush()
    return record
