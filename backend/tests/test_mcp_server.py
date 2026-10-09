"""MCP Server 用例：注册的工具必须是只读的，且执行时仍走权限与审计。"""

import json
import logging
import sys

import anyio
import pytest

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mcp import server as mcp_server

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
