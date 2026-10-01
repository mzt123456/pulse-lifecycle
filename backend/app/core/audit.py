"""审计日志：写入工具与中间件。

约定：
- 业务增删改在业务层用 record_audit 挂到当前事务上，随业务一起提交或回滚，
  避免出现"操作失败却留下成功记录"；
- 登录、登出、权限拒绝这类安全事件用 write_audit 立即落库（即使请求随后失败）；
- 中间件负责兜底记录其余写操作与导出、附件下载，请求会话已关闭，故独立开会话。
"""

import json
import logging
import re
from typing import Any

import jwt
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.timeutil import local_now
from app.db.session import get_session_factory
from app.models.system import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# 认证接口需要记录用户名，在业务层写，避免中间件重复记录
SKIP_PREFIXES = ("/api/v1/auth",)
# 导出与附件下载虽然读数据，但属于需要留痕的动作
AUDIT_GET_PATTERNS = (re.compile(r"/export$"), re.compile(r"/attachments/\d+$"))
PATH_PATTERN = re.compile(r"^/api/v1/(?P<name>[a-z0-9\-]+)(?:/(?P<object_id>\d+))?")


def _build_row(
    *,
    action: str,
    user_id: int | None = None,
    username: str | None = None,
    object_type: str | None = None,
    object_id: int | None = None,
    detail: str | None = None,
    client_ip: str | None = None,
) -> AuditLog:
    return AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        object_type=object_type,
        object_id=object_id,
        detail=detail,
        client_ip=client_ip,
        created_at=local_now(),
    )


def record_audit(db: Session, **kwargs: Any) -> None:
    """挂到当前会话，随业务事务一起提交或回滚。"""
    db.add(_build_row(**kwargs))


def write_audit(**kwargs: Any) -> None:
    """立即落库，用于登录失败、权限拒绝等即使请求失败也要留痕的事件。"""
    session = get_session_factory()()
    try:
        row = _build_row(**kwargs)
        if row.username is None and row.user_id is not None:
            user = session.get(User, row.user_id)
            row.username = user.username if user else None
        session.add(row)
        session.commit()
    except Exception:  # 审计失败不能影响业务
        session.rollback()
        logger.exception("写审计日志失败：%s", kwargs.get("action"))
    finally:
        session.close()


def _user_id_from_scope(scope: Scope) -> int | None:
    """从请求头里的访问令牌解出用户 ID；解析失败按匿名处理。"""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            token = value.decode("latin-1").split(" ", 1)[-1]
            settings = get_settings()
            try:
                payload = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                    options={"verify_exp": False},  # 过期令牌也留痕
                )
                subject = payload.get("sub")
                return int(subject) if subject else None
            except Exception:
                return None
    return None


class AuditMiddleware:
    """兜底记录写操作、导出与附件下载。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def should_audit(method: str, path: str) -> bool:
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            return False
        if method in AUDIT_METHODS:
            return True
        return any(pattern.search(path) for pattern in AUDIT_GET_PATTERNS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        if not self.should_audit(method, path):
            await self.app(scope, receive, send)
            return

        status = {"code": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        self._write(scope, method, path, status["code"])

    @staticmethod
    def _write(scope: Scope, method: str, path: str, status_code: int) -> None:
        match = PATH_PATTERN.match(path)
        object_type = match.group("name") if match else None
        object_id = int(match.group("object_id")) if match and match.group("object_id") else None
        query = scope.get("query_string", b"").decode("latin-1")
        client = scope.get("client")
        detail = json.dumps(
            {
                "method": method,
                "path": path,
                "status": status_code,
                "query": query or None,
            },
            ensure_ascii=False,
        )
        write_audit(
            action=f"{method} {path}",
            user_id=_user_id_from_scope(scope),
            object_type=object_type,
            object_id=object_id,
            detail=detail,
            client_ip=client[0] if client else None,
        )


def list_audit_logs(
    db: Session,
    *,
    user_id: int | None = None,
    action: str | None = None,
    object_type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AuditLog], int]:
    """审计日志只提供查询与导出，不提供修改与删除接口（编写报告 7.3）。"""
    stmt = select(AuditLog)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"%{action.strip()}%"))
    if object_type:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if start is not None:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end is not None:
        stmt = stmt.where(AuditLog.created_at <= end)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.execute(
            stmt.order_by(AuditLog.id.desc()).limit(page_size).offset((page - 1) * page_size)
        ).scalars()
    )
    return items, total
