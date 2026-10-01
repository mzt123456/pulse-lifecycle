"""认证业务：登录校验、锁定策略、令牌签发与撤销。"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import BusinessError, ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.core.timeutil import local_now, to_local_naive
from app.models.user import Permission, RefreshToken, Role, RolePermission, User, UserRole


def load_roles_and_permissions(db: Session, user: User) -> tuple[list[str], list[str]]:
    """取用户的角色名与权限点编码。"""
    roles = list(
        db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
            .order_by(Role.name)
        ).scalars()
    )
    permissions = list(
        db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user.id)
            .distinct()
            .order_by(Permission.code)
        ).scalars()
    )
    return roles, permissions


def authenticate(
    db: Session,
    username: str,
    password: str,
    client_ip: str | None = None,
    settings: Settings | None = None,
) -> User:
    """校验账号密码。失败累计次数，超过阈值锁定账号。"""
    settings = settings or get_settings()
    now = local_now()

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "用户名或密码错误", 401)

    if not user.is_active:
        raise BusinessError(ErrorCode.FORBIDDEN, "账号已停用，请联系管理员", 403)

    if user.locked_until is not None and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise BusinessError(ErrorCode.FORBIDDEN, f"账号已锁定，请 {minutes} 分钟后再试", 403)

    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.max_login_attempts:
            user.locked_until = now + timedelta(seconds=settings.lockout_duration_seconds)
            user.failed_attempts = 0
        db.commit()
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "用户名或密码错误", 401)

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = client_ip
    db.commit()
    return user


def issue_tokens(
    db: Session,
    user: User,
    client_ip: str | None = None,
    user_agent: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """签发访问令牌与刷新令牌，并把刷新令牌登记入库以便撤销。"""
    settings = settings or get_settings()
    access_token, _, _ = create_access_token(user.id, settings)
    refresh_token, refresh_id, refresh_expires = create_refresh_token(user.id, settings)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_id=refresh_id,
            expires_at=to_local_naive(refresh_expires),
            client_ip=client_ip,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    db.commit()

    roles, permissions = load_roles_and_permissions(db, user)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "department": user.department,
            "roles": roles,
            "permissions": permissions,
        },
    }


def _load_token_record(db: Session, token_id: str) -> RefreshToken:
    record = db.execute(
        select(RefreshToken).where(RefreshToken.token_id == token_id)
    ).scalar_one_or_none()
    if record is None:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "刷新令牌无效", 401)
    if record.revoked_at is not None:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "刷新令牌已撤销", 401)
    if record.expires_at <= local_now():
        raise BusinessError(ErrorCode.TOKEN_EXPIRED, "刷新令牌已过期", 401)
    return record


def refresh(
    db: Session,
    refresh_token: str,
    client_ip: str | None = None,
    user_agent: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """用刷新令牌换新令牌，旧刷新令牌立即撤销（轮换）。"""
    settings = settings or get_settings()
    payload = decode_token(refresh_token, "refresh", settings)
    record = _load_token_record(db, str(payload["jti"]))

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "账号不存在或已停用", 401)

    record.revoked_at = local_now()
    db.commit()
    return issue_tokens(db, user, client_ip, user_agent, settings)


def logout(db: Session, refresh_token: str, settings: Settings | None = None) -> None:
    """注销：撤销刷新令牌。令牌无法解析时按已失效处理，不报错。"""
    settings = settings or get_settings()
    try:
        payload = decode_token(refresh_token, "refresh", settings)
    except BusinessError:
        return

    record = db.execute(
        select(RefreshToken).where(RefreshToken.token_id == str(payload["jti"]))
    ).scalar_one_or_none()
    if record is not None and record.revoked_at is None:
        record.revoked_at = local_now()
        db.commit()
