"""MCP Server：同一套工具定义，第二个出口。

为什么值得单独做一层出口：HTTP 接口服务的是本系统的前端，而 MCP 服务的是
**任意支持该协议的客户端**（Claude Code、Codex、Cursor 等）。工具定义与权限
校验都复用 `app/ai/tools.py`，这里只负责协议适配与身份解析，不存在第二套实现。

身份怎么来：stdio 传输由本地进程拉起，没有 HTTP 请求头可承载 JWT，所以用
环境变量指定的**服务账号**（`MCP_USERNAME`，默认 admin）。这不是绕过权限——
工具层照旧按该账号的权限点过滤，账号没有的权限，工具会返回结构化拒绝。

默认只读：暴露的全部是查询与诊断工具，写操作（新增、修改、删除）不开放，
避免任何客户端一句话就把生产数据改掉。

运行：

    python -m app.mcp.server                                   # stdio
    MCP_TRANSPORT=streamable-http python -m app.mcp.server     # 内网 HTTP
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import agent, tools
from app.ai.llm import build_chat_client
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.mcp.auth import MCPAuthMiddleware, principal_user_id
from app.models.system import AuditLog
from app.models.user import User
from app.services.auth import load_roles_and_permissions

logger = logging.getLogger(__name__)

# stdio 传输下标准输出是 JSON-RPC 通道，日志一律走标准错误，
# 否则一行日志就会让客户端解析失败。
LOG_STREAM = sys.stderr


def _service_user(session: Session) -> User | None:
    """HTTP 传输用调用者自己的账号；stdio 用服务账号。

    令牌已经过 MCPAuthMiddleware 校验，这里只负责把用户取出来并确认仍然可用。
    """
    principal_id = principal_user_id.get()
    if principal_id is not None:
        user = session.get(User, principal_id)
        if user is None or not user.is_active:
            logger.warning("MCP 调用者账号不可用：id=%s", principal_id)
            return None
        return user

    username = os.getenv("MCP_USERNAME") or get_settings().initial_admin_username
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        logger.warning("MCP 服务账号不可用：%s", username)
    return user


def _registry() -> dict[str, tools.ToolSpec]:
    """工具注册表：业务查询工具 + 诊断工具。"""
    llm = build_chat_client(get_settings())
    return {**tools.TOOLS_BY_NAME, "diagnose_fault": agent.build_diagnose_tool(llm)}


def execute(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一的执行入口：独立会话 + 服务账号 + 权限校验 + 审计留痕。"""
    factory = get_session_factory()
    with factory() as session:
        user = _service_user(session)
        if user is None:
            return {"ok": False, "tool": tool_name, "error": "MCP 服务账号不存在或已停用"}
        _, permissions = load_roles_and_permissions(session, user)
        ctx = tools.ToolContext(
            db=session,
            user=user,
            permissions=frozenset(permissions),
            client_ip="mcp",
        )
        result = tools.run_tool(ctx, tool_name, arguments or {}, registry=_registry())
        session.commit()  # 审计随业务会话一起落库
        return result


def _json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str, indent=2)


def build_server() -> Any:
    """构造 MCP Server；导入放在函数内，避免没装 SDK 时影响主应用启动。"""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        "pulse-lifecycle",
        instructions=(
            "剪切阀脉冲器全生命周期管理系统的数据与诊断工具。"
            "查询类问题优先调用对应工具，不要凭印象回答；"
            "故障归因用 diagnose_fault，它返回的结论都带案例引用。"
        ),
    )

    @server.tool(description="查询系统整体概览：设备总数与状态分布、待维保设备数、低库存耗材数、未解决故障数。")
    def query_overview() -> str:
        return _json(execute("query_overview"))

    @server.tool(description="按编号关键字或状态查询设备台账。")
    def query_equipment(keyword: str | None = None, status: str | None = None, limit: int = 10) -> str:
        return _json(execute("query_equipment", {"keyword": keyword, "status": status, "limit": limit}))

    @server.tool(description="查询故障记录：现象、原因、解决方案与处理状态。")
    def query_fault_history(
        equipment_no: str | None = None,
        fault_type: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> str:
        return _json(
            execute(
                "query_fault_history",
                {
                    "equipment_no": equipment_no,
                    "fault_type": fault_type,
                    "status": status,
                    "limit": limit,
                },
            )
        )

    @server.tool(description="查询维保工单：工单号、维保等级、状态、起止日期、结果与建议。")
    def query_maintenance_orders(
        equipment_no: str | None = None,
        level: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> str:
        return _json(
            execute(
                "query_maintenance_orders",
                {"equipment_no": equipment_no, "level": level, "status": status, "limit": limit},
            )
        )

    @server.tool(description="查询耗材库存：部件号、描述、当前库存、安全库存与是否低库存。")
    def query_consumables(
        keyword: str | None = None, low_stock_only: bool = False, limit: int = 10
    ) -> str:
        return _json(
            execute(
                "query_consumables",
                {"keyword": keyword, "low_stock_only": low_stock_only, "limit": limit},
            )
        )

    @server.tool(description="查询使用记录（下井作业）：井号、起止时间、使用时长、进尺与作业人员。")
    def query_well_operations(
        equipment_no: str | None = None, well_no: str | None = None, limit: int = 10
    ) -> str:
        return _json(
            execute(
                "query_well_operations",
                {"equipment_no": equipment_no, "well_no": well_no, "limit": limit},
            )
        )

    @server.tool(description="故障案例检索与归因：输入现象，返回可能原因、建议处置与引用到的案例。")
    def diagnose_fault(
        description: str,
        equipment_no: str | None = None,
        fault_type: str | None = None,
    ) -> str:
        return _json(
            execute(
                "diagnose_fault",
                {"description": description, "equipment_no": equipment_no, "fault_type": fault_type},
            )
        )

    @server.tool(description="查询基础字典：设备状态、仪器类型、故障类型、维保等级等可选取值。")
    def query_dict_items(category: str | None = None) -> str:
        # 与其它工具走同一条路：同一套权限判定与审计留痕
        return _json(execute("query_dict_items", {"category": category}))

    @server.resource("pulse://corpus/stats", description="知识库语料规模与来源构成")
    def corpus_stats_resource() -> str:
        from app.ai import corpus as corpus_module

        factory = get_session_factory()
        with factory() as session:
            settings = get_settings()
            return json.dumps(
                corpus_module.corpus_stats(session, include_synthetic=settings.ai_include_synthetic),
                ensure_ascii=False,
            )

    @server.resource("pulse://audit/recent", description="最近的 AI 工具调用审计记录")
    def recent_tool_audit_resource() -> str:
        factory = get_session_factory()
        with factory() as session:
            rows = list(
                session.execute(
                    select(AuditLog)
                    .where(AuditLog.object_type == "ai_tool")
                    .order_by(AuditLog.id.desc())
                    .limit(20)
                ).scalars()
            )
            total = session.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.object_type == "ai_tool")
            )
            return json.dumps(
                {
                    "total": total or 0,
                    "items": [
                        {
                            "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                            "username": row.username,
                            "action": row.action,
                            "detail": row.detail,
                        }
                        for row in rows
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )

    return server


def main() -> None:
    settings = get_settings()
    configure_logging(settings, stream=LOG_STREAM)
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    server = build_server()
    logger.info("启动 MCP Server（传输方式：%s）", transport)

    if transport == "streamable-http":
        # HTTP 是别人能访问的端点，日志可以走标准输出；身份走访问令牌
        import uvicorn

        app = server.streamable_http_app(host=settings.mcp_host)
        app.add_middleware(MCPAuthMiddleware, require_token=settings.mcp_require_token)
        logger.info(
            "HTTP 传输监听 %s:%s，要求访问令牌：%s",
            settings.mcp_host,
            settings.mcp_port,
            settings.mcp_require_token,
        )
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port, log_level="info")
        return

    server.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
