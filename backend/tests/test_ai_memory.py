"""短期会话记忆用例：续接、归属、过期与容量上限，以及问答接口上的表现。

模型仍然是脚本化的假客户端，测试不依赖网络。
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.ai.llm import ChatTurn
from app.ai.memory import ConversationMemory, get_memory
# 复用 Agent 用例里的脚本化模型与 llm_override 夹具：伪造模型的行为在那边已经测过，
# 这里只关心记忆是怎么接上去的
from tests.test_ai_agent import ScriptedLLM, _content, _roles, llm_override  # noqa: F401

ASK = "/api/v1/ai/ask"
CONVERSATIONS = "/api/v1/ai/conversations"


@pytest.fixture(autouse=True)
def clean_memory():
    """每项用例前后都清空进程内会话，避免用例之间互相带上下文。"""
    get_memory().reset()
    yield
    get_memory().reset()


# ------------------------------------------------------------------ 存储层


def test_resolve_returns_empty_for_unknown_conversation() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)

    assert memory.resolve(None, 1) == []
    assert memory.resolve("不存在的会话", 1) == []  # 非法 ID 也当没有，不抛异常


def test_memory_keeps_only_recent_turns() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5, max_turns=3)
    conversation_id = memory.append(None, 1, "问题一", "答案一")

    for index in range(2, 6):
        memory.append(conversation_id, 1, f"问题{index}", f"答案{index}")

    turns = memory.resolve(conversation_id, 1)
    assert [question for question, _ in turns] == ["问题3", "问题4", "问题5"]
    assert turns[-1] == ("问题5", "答案5")


def test_answer_is_optional() -> None:
    """模型不可用时只有问题，也要能接上下文（下一轮只发 user 消息）。"""
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)
    conversation_id = memory.append(None, 1, "设备情况怎么样", None)

    assert memory.resolve(conversation_id, 1) == [("设备情况怎么样", None)]


def test_long_text_is_truncated() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5, max_chars=10)
    conversation_id = memory.append(None, 1, "问" * 50, "答" * 50)

    question, answer = memory.resolve(conversation_id, 1)[0]
    assert len(question) == 10
    assert answer is not None and len(answer) == 10


def test_conversation_is_bound_to_owner() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)
    conversation_id = memory.append(None, user_id=1, question="设备情况怎么样", answer="共 4 台。")

    # 换成别人：读不到，也写不进原会话
    assert memory.resolve(conversation_id, user_id=2) == []
    other_id = memory.append(conversation_id, user_id=2, question="那耗材呢", answer="共 2 种。")

    assert other_id != conversation_id
    assert memory.resolve(conversation_id, user_id=1) == [("设备情况怎么样", "共 4 台。")]
    assert memory.resolve(other_id, user_id=2) == [("那耗材呢", "共 2 种。")]


def test_expired_conversation_is_dropped() -> None:
    memory = ConversationMemory(ttl_seconds=0.05, max_conversations=5)
    conversation_id = memory.append(None, 1, "设备情况怎么样", "共 4 台。")

    time.sleep(0.08)

    assert memory.resolve(conversation_id, 1) == []
    assert memory.stats()["conversations"] == 0


def test_least_recently_used_conversation_is_evicted() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=2)
    first = memory.append(None, 1, "问题一", "答案一")
    second = memory.append(None, 1, "问题二", "答案二")
    memory.resolve(first, 1)  # 碰一下 first，让 second 变成最久未活跃

    third = memory.append(None, 1, "问题三", "答案三")

    assert memory.resolve(second, 1) == []
    assert memory.resolve(first, 1)
    assert memory.resolve(third, 1)
    assert memory.stats()["conversations"] == 2


def test_unknown_conversation_id_gets_a_new_one() -> None:
    """会话 ID 由服务端发放：不认识的 ID 不当成会话键，直接发一个新的。"""
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)

    conversation_id = memory.append("客户端自己编的会话", 1, "问题", "答案")

    assert conversation_id != "客户端自己编的会话"
    assert len(conversation_id) == 32  # uuid4().hex


def test_clear_removes_only_own_conversation() -> None:
    memory = ConversationMemory(ttl_seconds=60, max_conversations=5)
    conversation_id = memory.append(None, 1, "问题", "答案")

    assert memory.clear(conversation_id, 2) is False
    assert memory.clear(conversation_id, 1) is True
    assert memory.clear(conversation_id, 1) is False  # 再删一次也不会报错


# ------------------------------------------------------------------ 接口


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

    # 追问：不重复带历史，只带会话 ID
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


def test_request_history_is_still_the_fallback(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    """服务端没有这个会话（比如刚重启）时，仍然能用请求体带来的历史续上。"""
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


def test_degraded_answer_still_keeps_the_question(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    """模型不可用时没有答案，但问题要记下来，下一轮才接得上。"""
    llm_override(None)

    first = api_client.post(ASK, headers=readonly_headers, json={"question": "设备整体情况怎么样"})
    data = first.json()["data"]
    assert data["degraded"] is True
    conversation_id = data["conversation_id"]
    assert conversation_id

    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    follow_up = api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那耗材还剩多少", "conversation_id": conversation_id},
    ).json()["data"]

    assert follow_up["history_turns"] == 1
    # 上一轮没有答案，只发 user 消息
    assert _roles(llm.calls[0]["messages"]) == ["system", "user", "user"]


def test_forget_conversation_clears_memory(
    api_client: TestClient, readonly_headers: dict[str, str], llm_override
) -> None:
    llm_override(ScriptedLLM([ChatTurn(content="共 4 台设备。")]))
    conversation_id = api_client.post(
        ASK, headers=readonly_headers, json={"question": "设备整体情况怎么样"}
    ).json()["data"]["conversation_id"]

    removed = api_client.delete(f"{CONVERSATIONS}/{conversation_id}", headers=readonly_headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["removed"] is True

    llm = llm_override(ScriptedLLM([ChatTurn(content="共 2 种耗材。")]))
    follow_up = api_client.post(
        ASK,
        headers=readonly_headers,
        json={"question": "那耗材还剩多少", "conversation_id": conversation_id},
    ).json()["data"]

    assert follow_up["history_turns"] == 0
    assert _roles(llm.calls[0]["messages"]) == ["system", "user"]

    # 再删一次：幂等，不报错
    again = api_client.delete(f"{CONVERSATIONS}/{conversation_id}", headers=readonly_headers)
    assert again.status_code == 200
    assert again.json()["data"]["removed"] is False


def test_forget_conversation_requires_login(api_client: TestClient) -> None:
    response = api_client.delete(f"{CONVERSATIONS}/whatever")

    assert response.status_code == 401
