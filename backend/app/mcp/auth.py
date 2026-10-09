"""MCP 的身份解析：stdio 用服务账号，HTTP 用调用者自己的访问令牌。

为什么不能一律用服务账号：stdio 是本地进程拉起的，没有请求头可以承载身份；
但 HTTP 传输是**别人能访问的端点**，再退化成服务账号就等于把整个系统
以管理员身份对外开放。所以 HTTP 传输默认要求 `Authorization: Bearer <访问令牌>`，
并且把令牌里的用户作为本次调用的身份——权限点照旧按这个用户算。

令牌校验复用主应用的 `decode_token`：MCP 不另起一套认证体系，
用户停用、令牌过期这些状态与 HTTP 接口保持一致。
"""

from __future__ import annotations

import contextvars
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings
from app.core.security import decode_token

logger = logging.getLogger(__name__)

# 当前请求的调用者；None 表示 stdio 场景，用服务账号
principal_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "mcp_principal_user_id", default=None
)


def _extract_bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            text = value.decode("latin-1").strip()
            if text.lower().startswith("bearer "):
                return text[7:].strip() or None
    return None


class MCPAuthMiddleware:
    """纯 ASGI 中间件：校验访问令牌，并把用户 ID 放进 contextvar。

    用原生 ASGI 而不是 BaseHTTPMiddleware，是为了避免上下文在子任务里被复制丢失——
    工具调用发生在下游调用栈里，必须能读到当前请求的身份。
    """

    def __init__(self, app: ASGIApp, *, require_token: bool = True) -> None:
        self.app = app
        self.require_token = require_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _extract_bearer(scope)
        if token is None:
            if self.require_token:
                logger.warning("MCP 请求缺少访问令牌：%s", scope.get("path"))
                await JSONResponse(
                    {"error": "missing_token", "message": "请在 Authorization 头中提供访问令牌"},
                    status_code=401,
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        try:
            payload = decode_token(token, "access")
            user_id = int(payload["sub"])
        except Exception as exc:  # 过期、签名不符、格式不对一律按未授权处理
            logger.warning("MCP 访问令牌校验失败：%s", exc)
            await JSONResponse(
                {"error": "invalid_token", "message": "访问令牌无效或已过期"},
                status_code=401,
            )(scope, receive, send)
            return

        reset = principal_user_id.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            principal_user_id.reset(reset)


def require_token_default() -> bool:
    """HTTP 传输默认要求令牌；显式设 MCP_REQUIRE_TOKEN=false 才允许匿名（仅限本机调试）。"""
    return get_settings().mcp_require_token
