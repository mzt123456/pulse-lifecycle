"""使用记录接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.operation import WellOperation
from app.models.user import User
from app.schemas.well_operation import (
    WellOperationCreate,
    WellOperationOut,
    WellOperationUpdate,
)
from app.services import well_operation as service

router = APIRouter(prefix="/well-operations", tags=["使用管理"])


def _serialize(operation: WellOperation) -> dict:
    return WellOperationOut.model_validate(operation).model_dump(mode="json")


@router.get("", response_model=ApiResponse, summary="使用记录分页查询")
def list_operations(
    equipment_id: int | None = Query(default=None, description="按设备过滤"),
    well_no: str | None = Query(default=None, description="按井号模糊查询"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("well_operation.view")),
) -> dict:
    items, total = service.list_operations(db, equipment_id, well_no, page, page_size)
    return ok(
        {
            "items": [_serialize(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("", response_model=ApiResponse, summary="新增使用记录")
def create_operation(
    payload: WellOperationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("well_operation.create")),
) -> dict:
    return ok(_serialize(service.create_operation(db, payload, user)))


@router.get("/{operation_id}", response_model=ApiResponse, summary="使用记录详情")
def get_operation(
    operation_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("well_operation.view")),
) -> dict:
    return ok(_serialize(service.get_operation(db, operation_id)))


@router.put("/{operation_id}", response_model=ApiResponse, summary="修改使用记录")
def update_operation(
    operation_id: int,
    payload: WellOperationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("well_operation.update")),
) -> dict:
    return ok(_serialize(service.update_operation(db, operation_id, payload, user)))


@router.delete("/{operation_id}", response_model=ApiResponse, summary="删除使用记录")
def delete_operation(
    operation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("well_operation.delete")),
) -> dict:
    service.delete_operation(db, operation_id, user)
    return ok(None, "已删除")
