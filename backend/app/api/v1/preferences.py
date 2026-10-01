"""用户界面偏好接口：任何登录用户都可以读写自己的偏好。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.preference import PreferencesUpdate
from app.services import preference as service

router = APIRouter(prefix="/user-preferences", tags=["系统"])


@router.get("", response_model=ApiResponse, summary="读取当前用户的界面偏好")
def get_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return ok(service.get_or_create(db, user).model_dump())


@router.put("", response_model=ApiResponse, summary="保存当前用户的界面偏好")
def save_preferences(
    payload: PreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return ok(service.update(db, user, payload).model_dump())
