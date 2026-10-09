"""MCP Server 用例：注册的工具必须是只读的，且执行时仍走权限与审计。"""

import json
import logging
import sys

import anyio
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mcp import auth as mcp_auth
from app.mcp import server as mcp_server
from app.models.system import AuditLog
from app.models.user import User

# 写操作绝不能出现在 MCP 出口上：任何客户端一句话就能改生产数据的口子不能开
WRITE_HINTS = ("create", "update", "delete", "import", "issue", "login", "upload")


def _run(coro):
    return anyio.run(lambda: coro)


def test_registered_tools_are_read_only() -> None:
    mcp = mcp_server.build_server()
    names = [item.name for item in _run(mcp.list_tools())]

    assert "query_equipment" in names
    assert "diagnose_fault" in names
    assert not [name for name in names if any(hint in name for hint in WRITE_HINTS)]


def test_registered_resources_cover_corpus_and_audit() -> None:
    mcp = mcp_server.build_server()
    uris = [str(item.uri) for item in _run(mcp.list_resources())]

    assert "pulse://corpus/stats" in uris
    assert "pulse://audit/recent" in uris


def test_execute_returns_structured_result_and_writes_audit(
    auth_headers: dict[str, str], session_factory
) -> None:
    result = mcp_server.execute("query_overview", {})

    assert result["ok"] is True
    assert "equipment_total" in result

    from sqlalchemy import select

    from app.models.system import AuditLog

    with session_factory() as session:
        row = session.execute(
            select(AuditLog).where(AuditLog.action == "ai.tool.query_overview")
        ).scalars().first()
    assert row is not None
    assert json.loads(row.detail)["ok"] is True


def test_execute_rejects_tool_outside_registry() -> None:
    result = mcp_server.execute("delete_equipment", {"equipment_id": 1})

    assert result["ok"] is False
    assert "没有名为" in result["error"]


def test_dict_tool_goes_through_tool_layer_and_audits(auth_headers: dict[str, str], session_factory) -> None:
    """基础字典以前是绕开工具层的特例，现在与其它工具同一条路（含审计）。"""
    result = mcp_server.execute("query_dict_items", {})

    assert result["ok"] is True
    assert "仪器类型" in result["items"]

    with session_factory() as session:
        row = session.execute(
            select(AuditLog)
            .where(AuditLog.action == "ai.tool.query_dict_items")
            .order_by(AuditLog.id.desc())
        ).scalars().first()
    assert row is not None


def test_service_user_missing_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_USERNAME", "no-such-account")

    result = mcp_server.execute("query_overview", {})

    assert result["ok"] is False
    assert "服务账号" in result["error"]


def test_stdio_logs_go_to_stderr_not_stdout() -> None:
    """stdio 传输下 stdout 是协议通道，日志必须走 stderr。"""
    assert mcp_server.LOG_STREAM is sys.stderr


def test_logging_can_be_redirected() -> None:
    import io

    buffer = io.StringIO()
    configure_logging(get_settings(), stream=buffer)
    try:
        logging.getLogger("test.mcp").info("写入重定向流")
        assert "写入重定向流" in buffer.getvalue()
    finally:
        configure_logging(get_settings())  # 还原成默认 stdout，避免影响其它用例


# ------------------------------------------------------------------ HTTP 鉴权


def _http_app():
    """只挂中间件的 MCP HTTP 应用，用内存 ASGI 传输直接打，省去真的起进程。"""
    app = mcp_server.build_server().streamable_http_app()
    app.add_middleware(mcp_auth.MCPAuthMiddleware, require_token=True)
    return app


def _post(path: str, headers: dict[str, str]) -> httpx.Response:
    async def call() -> httpx.Response:
        app = _http_app()
        transport = httpx.ASGITransport(app=app)
        # MCP 的会话管理器要在 lifespan 里建立任务组，绕过 lifespan 会直接报错
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as client:
                return await client.post(
                    path,
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                )

    return anyio.run(call)


def test_http_requires_token() -> None:
    response = _post("/mcp", {})

    assert response.status_code == 401
    assert response.json()["error"] == "missing_token"


def test_http_rejects_invalid_token() -> None:
    response = _post("/mcp", {"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_http_accepts_valid_token(auth_headers: dict[str, str]) -> None:
    # 带合法令牌时不再被鉴权拦下（后面 MCP 协议自己会校验请求体，这里只看不是 401）
    response = _post("/mcp", {"Authorization": auth_headers["Authorization"]})

    assert response.status_code != 401


def test_principal_overrides_service_account(
    readonly_headers: dict[str, str], session_factory: sessionmaker
) -> None:
    """带令牌时以调用者身份执行，审计里应是调用者而不是服务账号。"""
    with session_factory() as session:
        caller = session.execute(
            select(User).where(User.username == "readonly_test")
        ).scalar_one()
        caller_id = caller.id

    reset = mcp_auth.principal_user_id.set(caller_id)
    try:
        result = mcp_server.execute("query_overview", {})
    finally:
        mcp_auth.principal_user_id.reset(reset)

    assert result["ok"] is True
    with session_factory() as session:
        row = session.execute(
            select(AuditLog).where(AuditLog.action == "ai.tool.query_overview").order_by(AuditLog.id.desc())
        ).scalars().first()
    assert row is not None
    assert row.username == "readonly_test"
