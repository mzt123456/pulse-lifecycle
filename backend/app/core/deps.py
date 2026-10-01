"""依赖注入：数据库会话、当前用户与权限校验。"""

from collections.abc import Callable

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import BusinessError, ErrorCode
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.services.auth import load_roles_and_permissions

bearer_scheme = HTTPBearer(auto_error=False, description="访问令牌，格式 Bearer <token>")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "未登录或令牌缺失", status.HTTP_401_UNAUTHORIZED)

    payload = decode_token(credentials.credentials, "access")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "账号不存在或已停用", status.HTTP_401_UNAUTHORIZED)
    return user


def require_permission(code: str) -> Callable[[User, Session], User]:
    """按权限点校验接口访问，阶段 4 起逐接口挂载。"""

    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        _, permissions = load_roles_and_permissions(db, user)
        if code not in permissions:
            raise BusinessError(ErrorCode.FORBIDDEN, "无操作权限", status.HTTP_403_FORBIDDEN)
        return user

    return dependency
