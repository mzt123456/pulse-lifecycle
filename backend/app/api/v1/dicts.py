"""基础字典接口：供前端下拉选项使用。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.system import DictItem
from app.models.user import User
from app.services import dict as dict_service

router = APIRouter(prefix="/dict-items", tags=["系统"])


@router.get("", response_model=ApiResponse, summary="读取基础字典")
def list_dict_items(
    category: str | None = Query(default=None, description="不传则返回全部分类"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if category:
        categories = [category]
    else:
        categories = list(
            db.execute(
                select(DictItem.category).distinct().order_by(DictItem.category)
            ).scalars()
        )
    return ok({name: dict_service.options(db, name) for name in categories})
