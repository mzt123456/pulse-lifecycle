"""短期会话记忆用例：会话目录（归属 / TTL / 容量）与检查点里的实际上下文。

记忆内容存在 LangGraph 的检查点里，所以除了目录本身，还要验证
"追问时模型确实看到了上一轮"、"工具调用留在检查点里"、"旧消息会被裁掉"。
模型仍然是脚本化的假客户端，测试不依赖网络。
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.ai import agent, graph_agent
from app.ai.llm import ChatTurn, LLMError
from app.ai.memory import ConversationMemory, get_memory

# 复用 Agent 用例里的脚本化模型与 llm_override 夹具：伪造模型的行为在那边已经测过，
# 这里只关心记忆是怎么接上去的
from tests.test_ai_agent import (  # noqa: F401
    ScriptedLLM,
    _call,
    _content,
    _roles,
    admin_ctx,
    llm_override,
)

ASK = "/api/v1/ai/ask"
CONVERSATIONS = "/api/v1/ai/conversations"


@pytest.fixture(autouse=True)
def clean_memory():
    """每项用例前后都清空会话目录与检查点，避免用例之间互相带上下文。"""
    get_memory().reset()
    yield
    get_memory().reset()


# ------------------------------------------------------------------ 会话目录


def test_owns_only_registered_own_conversations() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)

    assert memory.owns(None, 1) is False
    assert memory.owns("不存在的会话", 1) is False

    conversation_id = memory.register(None, user_id=1)
    assert memory.owns(conversation_id, user_id=1) is True
    assert memory.owns(conversation_id, user_id=2) is False  # 别人的会话不算"有"


def test_register_issues_server_side_ids() -> None:
    """会话 ID 由服务端发放：客户端自带的 ID 不被采纳，已登记的 ID 才复用。"""
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)

    issued = memory.register(None, 1)
    assert len(issued) == 32  # uuid4().hex

    assert memory.register("客户端自己编的会话", 1) != "客户端自己编的会话"
    assert memory.register(issued, 1) == issued


def test_expired_conversation_is_forgotten() -> None:
    memory = ConversationMemory(ttl_seconds=0.05, max_conversations=5)
    conversation_id = memory.register(None, 1)

    time.sleep(0.08)

    assert memory.owns(conversation_id, 1) is False
    assert memory.stats()["conversations"] == 0


def test_least_recently_used_conversation_is_evicted() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=2)
    first = memory.register(None, 1)
    second = memory.register(None, 1)
    memory.register(first, 1)  # 碰一下 first，让 second 变成最久未活跃

    third = memory.register(None, 1)

    assert memory.owns(first, 1) is True
    assert memory.owns(second, 1) is False
    assert memory.owns(third, 1) is True
    assert memory.stats()["conversations"] == 2


def test_clear_removes_only_own_conversation() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)
    conversation_id = memory.register(None, 1)

    assert memory.clear(conversation_id, 2) is False
    assert memory.clear(conversation_id, 1) is True
    assert memory.clear(conversation_id, 1) is False  # 再删一次也不会报错


def test_prior_context_without_thread_is_empty() -> None:
    assert graph_agent.prior_context(None) == (0, 0)
    assert graph_agent.prior_context("从来没有跑过的会话") == (0, 0)


# ------------------------------------------------------------------ 检查点


def test_ask_endpoint_remembers_and_reuses_conversation(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    first = llm_override(ScriptedLLM([ChatTurn(content="共 4 台设备。")]))
    created = api_client.post(ASK, headers=readonly_headers, json={"question": "设备整体情况怎么样"})

    assert created.status_code == 200, created.text
    data = created.json()["data"]
    conversation_id = data["conversation_id"]
    assert conversation_id
    assert data["history_turns"] == 0
    assert data["memory_source"] == "none"

    # 追问：不重复带历史，只带会话 ID；上下文由检查点提供
    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    follow_up = api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那耗材还剩多少", "conversation_id": conversation_id},
    )

    assert follow_up.status_code == 200, follow_up.text
    follow = follow_up.json()["data"]
    assert follow["conversation_id"] == conversation_id
    assert follow["history_turns"] == 1
    assert follow["memory_source"] == "server"
    assert _roles(llm.calls[0]["messages"])[:4] == ["system", "user", "assistant", "user"]
    assert _content(llm.calls[0]["messages"][1]) == "设备整体情况怎么样"
    assert _content(llm.calls[0]["messages"][2]) == "共 4 台设备。"
    assert _content(first.calls[0]["messages"][-1]) == "设备整体情况怎么样"


def test_tool_calls_stay_in_the_checkpoint(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    """检查点存的是完整的图状态：上一轮的工具调用与工具返回都还在，不是只留正文。"""
    llm_override(
        ScriptedLLM([_call("query_overview"), ChatTurn(content="当前共 4 台设备。")])
    )
    conversation_id = api_client.post(
        ASK, headers=readonly_headers, json={"question": "设备整体情况怎么样"}
    ).json()["data"]["conversation_id"]

    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那耗材还剩多少", "conversation_id": conversation_id},
    )

    assert _roles(llm.calls[0]["messages"]) == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert "query_overview" in _content(llm.calls[0]["messages"][3])


def test_old_messages_are_trimmed_out_of_the_checkpoint(
    admin_ctx, llm_override
) -> None:
    """上下文预算是硬的：长对话下最早的消息会被裁掉，检查点不会无限增长。"""
    conversation_id = get_memory().register(None, admin_ctx.user.id)
    answer = "答" * 1200
    llm = ScriptedLLM([ChatTurn(content=answer) for _ in range(4)])

    for index in range(4):
        agent.answer(
            admin_ctx.db,
            question=f"第{index}个问题" + "问" * 1200,
            user=admin_ctx.user,
            permissions=admin_ctx.permissions,
            llm=llm,
            thread_id=conversation_id,
        )

    turns, chars = graph_agent.prior_context(conversation_id)
    assert turns < 4  # 4 轮里最早的那些已经被裁掉
    # 窗口按预算裁剪，本轮回答是在裁剪之后追加的，所以上限是"预算 + 一轮回答"
    assert chars <= graph_agent.MESSAGE_CHAR_BUDGET + len(answer)


def test_ask_endpoint_uses_client_history_as_fallback(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    """服务端没有这个会话（比如刚重启）时，仍然能用请求体带来的历史接上。"""
    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))

    response = api_client.post(
        ASK,
        headers=readonly_headers,
        json={
            "question": "那耗材还剩多少",
            "history": [{"question": "设备情况怎么样", "answer": "共 4 台。"}],
        },
    )

    data = response.json()["data"]
    assert data["memory_source"] == "client"
    assert data["history_turns"] == 1
    assert _content(llm.calls[0]["messages"][1]) == "设备情况怎么样"

    # 这一轮之后，历史已经落在检查点里，下一轮就不需要请求体再带了
    llm = llm_override(ScriptedLLM([ChatTurn(content="共 3 个工单。")]))
    follow = api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那维保工单呢", "conversation_id": data["conversation_id"]},
    ).json()["data"]
    assert follow["history_turns"] == 2
    assert follow["memory_source"] == "server"
    # 请求体里什么都没带，模型仍然看得到前两轮
    assert _roles(llm.calls[0]["messages"])[:4] == ["system", "user", "assistant", "user"]
    assert _content(llm.calls[0]["messages"][1]) == "设备情况怎么样"


def test_server_memory_wins_over_request_history(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    llm_override(ScriptedLLM([ChatTurn(content="共 4 台设备。")]))
    conversation_id = api_client.post(
        ASK, headers=readonly_headers, json={"question": "设备整体情况怎么样"}
    ).json()["data"]["conversation_id"]

    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    response = api_client.post(
        ASK,
        headers=readonly_headers,
        json={
            "question": "那耗材还剩多少",
            "conversation_id": conversation_id,
            "history": [{"question": "这段历史不该被采用", "answer": "假的"}],
        },
    )

    data = response.json()["data"]
    assert data["memory_source"] == "server"
    assert data["history_turns"] == 1
    assert _content(llm.calls[0]["messages"][1]) == "设备整体情况怎么样"


def test_failed_model_turn_is_still_remembered(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    """模型这一轮失败（超时/网关错），问题也在检查点里——下一轮接得上，但没有答案。"""
    llm_override(ScriptedLLM([LLMError("网关超时")]))

    first = api_client.post(ASK, headers=readonly_headers, json={"question": "设备整体情况怎么样"})
    data = first.json()["data"]
    assert data["degraded"] is True
    assert "大模型不可用" in (data["reason"] or "")
    conversation_id = data["conversation_id"]

    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    follow_up = api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那耗材还剩多少", "conversation_id": conversation_id},
    ).json()["data"]

    assert follow_up["history_turns"] == 1
    # 上一轮没有答案，只留下一条 user 消息
    assert _roles(llm.calls[0]["messages"]) == ["system", "user", "user"]


def test_conversation_is_not_shared_across_users(
    api_client: TestClient,
    auth_headers: dict[str, str],
    readonly_headers: dict[str, str],
    llm_override,
) -> None:
    llm_override(ScriptedLLM([ChatTurn(content="共 4 台设备。")]))
    conversation_id = api_client.post(
        ASK, headers=auth_headers, json={"question": "设备整体情况怎么样"}
    ).json()["data"]["conversation_id"]

    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    response = api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那耗材还剩多少", "conversation_id": conversation_id},
    )

    data = response.json()["data"]
    assert data["history_turns"] == 0  # 拿别人的会话 ID 也读不到内容
    assert data["memory_source"] == "none"
    assert data["conversation_id"] != conversation_id
    assert _roles(llm.calls[0]["messages"]) == ["system", "user"]
    # 自己的新会话没有污染别人的检查点
    assert graph_agent.prior_context(conversation_id)[0] == 1


def test_forget_conversation_clears_both_registry_and_checkpoint(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    llm_override(ScriptedLLM([ChatTurn(content="共 4 台设备。")]))
    conversation_id = api_client.post(
        ASK, headers=readonly_headers, json={"question": "设备整体情况怎么样"}
    ).json()["data"]["conversation_id"]
    assert graph_agent.prior_context(conversation_id)[0] == 1

    removed = api_client.delete(f"{CONVERSATIONS}/{conversation_id}", headers=readonly_headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["removed"] is True
    assert graph_agent.prior_context(conversation_id) == (0, 0)  # 检查点也删了

    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    follow_up = api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那耗材还剩多少", "conversation_id": conversation_id},
    ).json()["data"]

    assert follow_up["history_turns"] == 0
    assert follow_up["conversation_id"] != conversation_id  # 服务端另发一个新会话
    assert _roles(llm.calls[0]["messages"]) == ["system", "user"]

    # 再删一次：幂等，不报错
    again = api_client.delete(f"{CONVERSATIONS}/{conversation_id}", headers=readonly_headers)
    assert again.status_code == 200
    assert again.json()["data"]["removed"] is False


def test_forget_conversation_requires_login(api_client: TestClient) -> None:
    response = api_client.delete(f"{CONVERSATIONS}/whatever")

    assert response.status_code == 401
