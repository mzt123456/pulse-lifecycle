"""设备台账接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.equipment import Equipment
from app.models.user import User
from app.schemas.equipment import EquipmentCreate, EquipmentOut, EquipmentUpdate
from app.services import equipment as service

router = APIRouter(prefix="/equipment", tags=["设备管理"])


def _serialize(equipment: Equipment) -> dict:
    return EquipmentOut.model_validate(equipment).model_dump(mode="json")


@router.get("", response_model=ApiResponse, summary="设备台账分页查询")
def list_equipment(
    keyword: str | None = Query(default=None, description="按脉冲编号或型号模糊查询"),
    status: str | None = Query(default=None, description="按状态过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("equipment.view")),
) -> dict:
    items, total = service.list_equipment(db, keyword, status, page, page_size)
    return ok(
        {
            "items": [_serialize(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("", response_model=ApiResponse, summary="新增设备")
def create_equipment(
    payload: EquipmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("equipment.create")),
) -> dict:
    return ok(_serialize(service.create_equipment(db, payload, user)))


@router.get("/{equipment_id}", response_model=ApiResponse, summary="设备详情")
def get_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("equipment.view")),
) -> dict:
    return ok(_serialize(service.get_equipment(db, equipment_id)))


@router.put("/{equipment_id}", response_model=ApiResponse, summary="修改设备")
def update_equipment(
    equipment_id: int,
    payload: EquipmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("equipment.update")),
) -> dict:
    return ok(_serialize(service.update_equipment(db, equipment_id, payload, user)))


@router.delete("/{equipment_id}", response_model=ApiResponse, summary="删除设备")
def delete_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("equipment.delete")),
) -> dict:
    service.delete_equipment(db, equipment_id, user)
    return ok(None, "已删除")
