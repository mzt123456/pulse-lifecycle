"""认证接口：登录、刷新、注销与当前用户信息。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.ratelimit import client_ip, enforce_login_rate_limit
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post(
    "/login",
    response_model=ApiResponse,
    summary="登录",
    dependencies=[Depends(enforce_login_rate_limit)],
)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    ip = client_ip(request)
    user = auth_service.authenticate(db, payload.username, payload.password, ip)
    data = auth_service.issue_tokens(
        db, user, ip, request.headers.get("user-agent")
    )
    return ok(TokenResponse(**data).model_dump())


@router.post("/refresh", response_model=ApiResponse, summary="刷新访问令牌")
def refresh_token(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    data = auth_service.refresh(
        db, payload.refresh_token, client_ip(request), request.headers.get("user-agent")
    )
    return ok(TokenResponse(**data).model_dump())


@router.post("/logout", response_model=ApiResponse, summary="注销")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> dict:
    auth_service.logout(db, payload.refresh_token)
    return ok(None, "已注销")


@router.get("/me", response_model=ApiResponse, summary="获取当前用户")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    roles, permissions = auth_service.load_roles_and_permissions(db, user)
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "department": user.department,
            "roles": roles,
            "permissions": permissions,
        }
    )
