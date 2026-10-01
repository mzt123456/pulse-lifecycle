"""维保工单与步骤接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.maintenance import MaintenanceOrder, MaintenanceStep
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceOrderCreate,
    MaintenanceOrderDetail,
    MaintenanceOrderOut,
    MaintenanceOrderUpdate,
    MaintenanceStepOut,
    StepCompleteRequest,
)
from app.services import maintenance as service

router = APIRouter(prefix="/maintenance-orders", tags=["维保管理"])


def _serialize(order: MaintenanceOrder) -> dict:
    return MaintenanceOrderOut.model_validate(order).model_dump(mode="json")


def _serialize_detail(order: MaintenanceOrder) -> dict:
    return MaintenanceOrderDetail.model_validate(order).model_dump(mode="json")


def _serialize_step(step: MaintenanceStep) -> dict:
    return MaintenanceStepOut.model_validate(step).model_dump(mode="json")


@router.get("", response_model=ApiResponse, summary="维保工单分页查询")
def list_orders(
    equipment_id: int | None = Query(default=None, description="按设备过滤"),
    level: str | None = Query(default=None, description="按维保等级过滤"),
    status: str | None = Query(default=None, description="按状态过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("maintenance.view")),
) -> dict:
    items, total = service.list_orders(db, equipment_id, level, status, page, page_size)
    return ok(
        {
            "items": [_serialize(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("", response_model=ApiResponse, summary="创建维保工单（按等级生成步骤清单）")
def create_order(
    payload: MaintenanceOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("maintenance.create")),
) -> dict:
    return ok(_serialize_detail(service.create_order(db, payload, user)))


@router.get("/{order_id}", response_model=ApiResponse, summary="维保工单详情（含步骤清单）")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("maintenance.view")),
) -> dict:
    return ok(_serialize_detail(service.get_order(db, order_id)))


@router.put("/{order_id}", response_model=ApiResponse, summary="更新工单结果、油位与建议")
def update_order(
    order_id: int,
    payload: MaintenanceOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("maintenance.update")),
) -> dict:
    return ok(_serialize_detail(service.update_order(db, order_id, payload, user)))


@router.post("/{order_id}/steps/{step_id}", response_model=ApiResponse, summary="勾选步骤完成")
def complete_step(
    order_id: int,
    step_id: int,
    payload: StepCompleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("maintenance.update")),
) -> dict:
    return ok(_serialize_step(service.complete_step(db, order_id, step_id, payload, user)))
