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

    # 基础字典不挂业务权限点，属于"登录即可读"，所以总会出现在清单里
    assert names == {"query_equipment", "query_fault_history", "query_dict_items"}
    assert "query_consumables" not in names


def test_login_only_tool_is_available_without_business_permissions(
    admin_ctx: tools.ToolContext,
) -> None:
    ctx = tools.ToolContext(db=admin_ctx.db, user=admin_ctx.user, permissions=frozenset())

    exposed = {tool.name for tool in tools.tools_for(ctx.permissions)}
    result = tools.run_tool(ctx, "query_dict_items", {})

    assert exposed == {"query_dict_items"}
    assert result["ok"] is True
    assert "仪器类型" in result["items"]


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
    # 基础字典是登录即可读的配置数据，其余无权限的业务工具都不该出现
    assert exposed == {"query_equipment", "query_dict_items"}, "无权限的工具不该出现在模型可见的工具清单里"


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


# ------------------------------------------------------------------ 多轮


def test_history_is_prepended_in_order(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([ChatTurn(content="按上一轮说的继续。")])

    result = agent.answer(
        admin_ctx.db,
        question="那耗材还剩多少",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
        history=[
            {"question": "设备整体情况怎么样", "answer": "共 4 台设备。"},
            {"question": "耗材呢", "answer": "共 2 种。"},
        ],
    )

    roles = [item["role"] for item in llm.calls[0]["messages"]]
    contents = [item.get("content") for item in llm.calls[0]["messages"]]

    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert contents[1] == "设备整体情况怎么样"
    assert contents[2] == "共 4 台设备。"
    assert contents[-1] == "那耗材还剩多少"
    assert result["history_turns"] == 2


def test_history_entry_without_answer_only_sends_question(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([ChatTurn(content="好的。")])

    agent.answer(
        admin_ctx.db,
        question="继续查耗材",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
        history=[{"question": "设备情况", "answer": None}],
    )

    roles = [item["role"] for item in llm.calls[0]["messages"]]
    assert roles == ["system", "user", "user"]


def test_history_is_capped(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([ChatTurn(content="好。")])

    result = agent.answer(
        admin_ctx.db,
        question="再查一次耗材",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
        history=[{"question": f"第{i}个问题", "answer": f"第{i}个回答"} for i in range(12)],
    )

    assert result["history_turns"] == agent.MAX_HISTORY_TURNS
    # 只带最近几轮：最早的那几条不该出现
    contents = " ".join(str(item.get("content")) for item in llm.calls[0]["messages"])
    assert "第0个问题" not in contents
    assert "第11个问题" in contents


def test_follow_up_question_inherits_skill_from_history(admin_ctx: tools.ToolContext) -> None:
    """追问句本身没有触发词，靠上两轮的用户提问把技能带过来。"""
    llm = ScriptedLLM([ChatTurn(content="建议先检查密封面。")])
    follow_up = "那还有别的可能吗"

    with_history = agent.answer(
        admin_ctx.db,
        question=follow_up,
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
        history=[{"question": "下井后压力保持不住是什么原因", "answer": "可能是密封面拉伤。"}],
    )
    without_history = agent.answer(
        admin_ctx.db,
        question=follow_up,
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=ScriptedLLM([ChatTurn(content="请说明具体问题。")]),
    )

    assert with_history["skill"] == "fault_diagnosis"
    assert without_history["skill"] is None


def test_multi_turn_prompt_warns_history_may_be_stale(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([ChatTurn(content="重新查一遍。")])

    agent.answer(
        admin_ctx.db,
        question="耗材还剩多少",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
        history=[{"question": "耗材情况", "answer": "还有 2 个。"}],
    )

    system_prompt = llm.calls[0]["messages"][0]["content"]
    assert "可能已经过时" in system_prompt
    assert "重新调用工具" in system_prompt


def test_context_counts_history_chars(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([ChatTurn(content="好。")])

    result = agent.answer(
        admin_ctx.db,
        question="耗材还剩多少",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
        history=[{"question": "一二三四五", "answer": "六七八九十"}],
    )

    assert result["context_chars"]["history"] == 10


# ------------------------------------------------------------------ 编排


def test_default_orchestrator_is_langgraph(admin_ctx: tools.ToolContext) -> None:
    llm = ScriptedLLM([ChatTurn(content="共 4 台设备。")])

    result = agent.answer(
        admin_ctx.db,
        question="设备情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
    )

    assert result["orchestrator"] == "langgraph"


def test_loop_orchestrator_is_still_available(admin_ctx: tools.ToolContext) -> None:
    """手写循环保留作为对照与兜底：同样的输入应当给出同样的结果。"""
    turns = [_call("query_overview"), ChatTurn(content="当前共 4 台设备。")]

    loop_result = agent.answer(
        admin_ctx.db,
        question="设备情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=ScriptedLLM(list(turns)),
        orchestrator="loop",
    )
    graph_result = agent.answer(
        admin_ctx.db,
        question="设备情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=ScriptedLLM(list(turns)),
        orchestrator="langgraph",
    )

    assert loop_result["orchestrator"] == "loop"
    assert graph_result["orchestrator"] == "langgraph"
    assert loop_result["answer"] == graph_result["answer"]
    assert loop_result["used_tools"] == graph_result["used_tools"] == ["query_overview"]
    assert [step["tool"] for step in loop_result["steps"]] == [
        step["tool"] for step in graph_result["steps"]
    ]


def test_graph_nodes_are_explicit() -> None:
    """图是显式的：节点名字一眼能看出流程，这是选状态图而不是黑盒循环的理由。"""
    from app.ai import graph_agent

    nodes = set(graph_agent.build_graph().get_graph().nodes)

    assert {"prepare", "plan", "execute_tools", "partial"} <= nodes


def test_graph_failure_falls_back_to_loop(
    admin_ctx: tools.ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """图编排自身出问题时不能让问答失败，要退回手写循环并标明。"""
    from app.ai import graph_agent

    def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(graph_agent, "run", boom)
    llm = ScriptedLLM([ChatTurn(content="兜底回答。")])

    result = agent.answer(
        admin_ctx.db,
        question="设备情况怎么样",
        user=admin_ctx.user,
        permissions=admin_ctx.permissions,
        llm=llm,
    )

    assert result["answer"] == "兜底回答。"
    assert "回退" in result["orchestrator"]


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


def test_ask_endpoint_accepts_history(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))

    response = api_client.post(
        ASK,
        headers=readonly_headers,
        json={
            "question": "那耗材还剩多少",
            "history": [{"question": "设备情况怎么样", "answer": "共 4 台。"}],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["history_turns"] == 1
    assert data["context_chars"]["history"] > 0
    assert [item["role"] for item in llm.calls[0]["messages"]][:3] == [
        "system",
        "user",
        "assistant",
    ]


def test_ask_endpoint_rejects_overlong_history(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    response = api_client.post(
        ASK,
        headers=readonly_headers,
        json={
            "question": "耗材还剩多少",
            "history": [{"question": f"问题{i}", "answer": "答案"} for i in range(9)],
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40001
