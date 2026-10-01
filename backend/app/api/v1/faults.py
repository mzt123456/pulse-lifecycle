"""故障记录接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.fault import FaultRecord
from app.models.user import User
from app.schemas.fault import FaultRecordCreate, FaultRecordOut, FaultRecordUpdate
from app.services import fault as service

router = APIRouter(prefix="/fault-records", tags=["故障记录"])


def _serialize(record: FaultRecord) -> dict:
    return FaultRecordOut.model_validate(record).model_dump(mode="json")


@router.get("", response_model=ApiResponse, summary="故障记录分页查询")
def list_faults(
    equipment_id: int | None = Query(default=None, description="按设备过滤"),
    fault_type: str | None = Query(default=None, description="按故障类型过滤"),
    status: str | None = Query(default=None, description="按处理状态过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("fault.view")),
) -> dict:
    items, total = service.list_faults(db, equipment_id, fault_type, status, page, page_size)
    return ok(
        {
            "items": [_serialize(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("", response_model=ApiResponse, summary="新增故障记录")
def create_fault(
    payload: FaultRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("fault.create")),
) -> dict:
    return ok(_serialize(service.create_fault(db, payload, user)))


@router.get("/{fault_id}", response_model=ApiResponse, summary="故障记录详情")
def get_fault(
    fault_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("fault.view")),
) -> dict:
    return ok(_serialize(service.get_fault(db, fault_id)))


@router.put("/{fault_id}", response_model=ApiResponse, summary="更新原因、解决方案与状态")
def update_fault(
    fault_id: int,
    payload: FaultRecordUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("fault.update")),
) -> dict:
    return ok(_serialize(service.update_fault(db, fault_id, payload, user)))
