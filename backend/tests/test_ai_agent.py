"""Agent 与工具层用例：权限边界、循环收敛、步数上限与审计留痕。

模型一律用脚本化的假客户端，测试不依赖网络，也不会消耗真实额度。
"""

import copy
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai import agent, tools
from app.ai.llm import ChatTurn, LLMError, ToolCall
from app.api.v1.ai import get_chat_client
from app.models.system import AuditLog
from app.models.user import User
from app.services.auth import load_roles_and_permissions

ASK = "/api/v1/ai/ask"


class ScriptedLLM:
    """按脚本返回预设轮次，并记录每次调用收到的 messages 与工具清单。"""

    model = "fake-tool-model"

    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []
        self.json_calls: list[str] = []

    def complete_with_tools(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatTurn:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools})
        if not self.turns:
            raise AssertionError("模型被调用的次数超过了脚本预设")
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """诊断工具内部要的是 JSON 输出，这里给一个最小可用结果。"""
        self.json_calls.append(user)
        return {
            "causes": [{"text": "密封面拉伤", "case_ids": ["C1"]}],
            "actions": [{"text": "研磨密封面", "case_ids": ["C1"]}],
            "confidence": "中",
            "note": "",
        }


def _call(name: str, arguments: dict[str, Any] | None = None) -> ChatTurn:
    return ChatTurn(content=None, tool_calls=(ToolCall(id="c1", name=name, arguments=arguments or {}),))


@pytest.fixture
def llm_override(api_client: TestClient):
    def install(client_impl: Any) -> Any:
        api_client.app.dependency_overrides[get_chat_client] = lambda: client_impl
        return client_impl

    install(None)
    yield install
    api_client.app.dependency_overrides.pop(get_chat_client, None)


@pytest.fixture
def admin_ctx(
    session_factory: sessionmaker[Session],
    auth_headers: dict[str, str],
    test_admin: dict[str, str],
) -> tools.ToolContext:
    """借用 auth_headers 夹具确保管理员存在（迁移回退用例会清空业务数据）。"""
    with session_factory() as session:
        user = session.execute(
            select(User).where(User.username == test_admin["username"])
        ).scalar_one()
        _, permissions = load_roles_and_permissions(session, user)
        yield tools.ToolContext(db=session, user=user, permissions=frozenset(permissions))


# ------------------------------------------------------------------ 工具层


def test_tools_are_filtered_by_permission() -> None:
    names = {tool.name for tool in tools.tools_for(["equipment.view", "fault.view"])}

    assert names == {"query_equipment", "query_fault_history"}
    assert "query_consumables" not in names


def test_run_tool_denies_without_permission(admin_ctx: tools.ToolContext) -> None:
    ctx = tools.ToolContext(
        db=admin_ctx.db,
        user=admin_ctx.user,
        permissions=frozenset({"equipment.view"}),
    )

    result = tools.run_tool(ctx, "query_consumables", {})

    assert result["ok"] is False
    assert "权限" in result["error"]


def test_run_tool_reports_unknown_tool(admin_ctx: tools.ToolContext) -> None:
    result = tools.run_tool(admin_ctx, "drop_table", {})
    assert result["ok"] is False
    assert "没有名为" in result["error"]


def test_run_tool_writes_audit_row(admin_ctx: tools.ToolContext) -> None:
    tools.run_tool(admin_ctx, "query_overview", {})
    admin_ctx.db.flush()

    row = admin_ctx.db.execute(
        select(AuditLog).where(AuditLog.action == "ai.tool.query_overview")
    ).scalars().first()

    assert row is not None
    assert row.object_type == "ai_tool"
    assert json.loads(row.detail)["ok"] is True


def test_query_equipment_returns_trimmed_fields(admin_ctx: tools.ToolContext) -> None:
    result = tools.run_tool(admin_ctx, "query_equipment", {"limit": 1000})

    assert result["ok"] is True
    assert len(result["items"]) <= tools.MAX_LIMIT
    if result["items"]:
        item = result["items"][0]
        assert "equipment_no" in item
        # 上下文里不该出现备注、联系电话这类与问答无关的字段
        assert "remark" not in item
        assert "contact_phone" not in item


# ------------------------------------------------------------------ 循环


def test_agent_runs_tool_then_answers(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([_call("query_overview"), ChatTurn(content="当前共 4 台设备。")])

    result = agent.answer(
        admin_ctx.db,
        question="现在设备整体情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
    )

    assert result["answer"] == "当前共 4 台设备。"
    assert result["used_tools"] == ["query_overview"]
    assert result["steps"][0]["ok"] is True
    assert result["degraded"] is False

    # 工具结果必须以 tool 角色回灌，模型才有依据说下一句
    second_round = llm.calls[1]["messages"]
    assert second_round[-1]["role"] == "tool"
    assert second_round[-1]["tool_call_id"] == "c1"


def test_agent_hides_tools_without_permission(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([ChatTurn(content="只能查设备。")])

    agent.answer(
        admin_ctx.db,
        question="耗材还剩多少",
        user=admin_ctx.user,
        permissions=frozenset({"equipment.view"}),
        llm=llm,
    )

    exposed = {item["function"]["name"] for item in llm.calls[0]["tools"]}
    assert exposed == {"query_equipment"}, "无权限的工具不该出现在模型可见的工具清单里"


def test_agent_reports_tool_error_back_to_model(admin_ctx: tools.ToolContext) -> None:
    """模型调用了没暴露给它的工具时，工具层仍然要挡下来并把错误交回模型。"""
    llm = ScriptedLLM([_call("query_consumables"), ChatTurn(content="我没有耗材查看权限。")])

    result = agent.answer(
        admin_ctx.db,
        question="耗材还剩多少",
        user=admin_ctx.user,
        permissions=frozenset({"equipment.view"}),
        llm=llm,
    )

    payload = json.loads(llm.calls[1]["messages"][-1]["content"])
    assert payload["ok"] is False
    assert result["answer"] == "我没有耗材查看权限。"


def test_agent_stops_at_step_limit(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([_call("query_overview") for _ in range(10)])

    result = agent.answer(
        admin_ctx.db,
        question="设备整体情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
        max_steps=3,
    )

    assert len(result["steps"]) == 3
    assert result["answer"] is None
    assert result["degraded"] is True
    assert "步数上限" in result["reason"]


def test_agent_can_call_injected_diagnose_tool(admin_ctx: tools.ToolContext) -> None:
    """诊断工具是按轮注入的，必须同时进注册表，否则会报“没有名为…的工具”。"""
    llm = ScriptedLLM(
        [
            _call("diagnose_fault", {"description": "下井后压力保持不住，密封面渗漏"}),
            ChatTurn(content="按案例看，最可能是密封面拉伤。"),
        ]
    )

    result = agent.answer(
        admin_ctx.db,
        question="下井后压力保持不住，可能是什么原因",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
    )

    assert result["steps"][0]["tool"] == "diagnose_fault"
    assert result["steps"][0]["ok"] is True, result["steps"][0]["summary"]
    assert "没有名为" not in result["steps"][0]["summary"]


def test_agent_degrades_when_model_unavailable(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([LLMError("网关超时")])

    result = agent.answer(
        admin_ctx.db,
        question="设备整体情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
    )

    assert result["degraded"] is True
    assert "大模型不可用" in result["reason"]


def test_agent_without_client_returns_reason(admin_ctx: tools.ToolContext) -> None:
    result = agent.answer(
        admin_ctx.db,
        question="设备整体情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=None,
    )

    assert result["degraded"] is True
    assert "未配置大模型" in result["reason"]


# ------------------------------------------------------------------ 接口


def test_ask_endpoint_returns_answer_and_steps(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    llm_override(ScriptedLLM([_call("query_overview"), ChatTurn(content="当前共 4 台设备。")]))

    response = api_client.post(
        ASK, headers=readonly_headers, json={"question": "现在设备整体情况怎么样"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["answer"] == "当前共 4 台设备。"
    assert data["used_tools"] == ["query_overview"]
    assert data["steps"][0]["tool"] == "query_overview"
    assert data["context_chars"]["system_prompt"] > 0


def test_ask_endpoint_requires_login(api_client: TestClient, llm_override) -> None:
    response = api_client.post(ASK, json={"question": "设备整体情况怎么样"})
    assert response.status_code == 401


def test_ask_endpoint_rejects_short_question(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    response = api_client.post(ASK, headers=readonly_headers, json={"question": "查"})
    assert response.status_code == 400
    assert response.json()["code"] == 40001
