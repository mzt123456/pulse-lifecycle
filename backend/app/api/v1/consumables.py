"""耗材目录、批量导入与领用接口。"""

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.consumable import Consumable, ConsumableUsage
from app.models.user import User
from app.schemas.consumable import (
    ConsumableCreate,
    ConsumableOut,
    ConsumableUpdate,
    ConsumableUsageCreate,
    ConsumableUsageOut,
)
from app.services import consumable as service

router = APIRouter(prefix="/consumables", tags=["耗材管理"])


def _serialize(item: Consumable) -> dict:
    return ConsumableOut.model_validate(item).model_dump(mode="json")


def _serialize_usage(usage: ConsumableUsage) -> dict:
    return ConsumableUsageOut.model_validate(usage).model_dump(mode="json")


@router.get("", response_model=ApiResponse, summary="耗材目录分页查询")
def list_consumables(
    keyword: str | None = Query(default=None, description="按部件号或描述模糊查询"),
    low_stock_only: bool = Query(default=False, description="只看低于安全库存的"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("consumable.view")),
) -> dict:
    items, total = service.list_consumables(db, keyword, low_stock_only, page, page_size)
    return ok(
        {
            "items": [_serialize(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("", response_model=ApiResponse, summary="新增耗材")
def create_consumable(
    payload: ConsumableCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("consumable.create")),
) -> dict:
    return ok(_serialize(service.create_consumable(db, payload, user)))


@router.post("/import", response_model=ApiResponse, summary="按 Excel 批量导入目录")
async def import_consumables(
    file: UploadFile = File(description="Excel 文件（.xlsx）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("consumable.import")),
) -> dict:
    content = await file.read()
    result = service.import_consumables(db, content, user)
    return ok(result.model_dump())


@router.get("/usages", response_model=ApiResponse, summary="耗材领用明细")
def list_usages(
    consumable_id: int | None = Query(default=None, description="按耗材过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("consumable.view")),
) -> dict:
    items, total = service.list_usages(db, consumable_id, page, page_size)
    return ok(
        {
            "items": [_serialize_usage(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/usages", response_model=ApiResponse, summary="领用耗材并扣减库存")
def issue_consumable(
    payload: ConsumableUsageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("consumable.issue")),
) -> dict:
    return ok(_serialize_usage(service.issue_consumable(db, payload, user)))


@router.get("/{consumable_id}", response_model=ApiResponse, summary="耗材详情")
def get_consumable(
    consumable_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("consumable.view")),
) -> dict:
    return ok(_serialize(service.get_consumable(db, consumable_id)))


@router.put("/{consumable_id}", response_model=ApiResponse, summary="修改耗材目录")
def update_consumable(
    consumable_id: int,
    payload: ConsumableUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("consumable.create")),
) -> dict:
    return ok(_serialize(service.update_consumable(db, consumable_id, payload, user)))
