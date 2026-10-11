"""Agent 编排的 LangGraph 实现：把原来的手写循环写成显式状态图。

图长这样：

```
START → prepare（选技能、拼提示词、设预算）
          ↓
        plan（让模型决定：调工具 还是 给结论）
          ├── 要调工具 → execute_tools（执行 + 写审计 + 结果回灌）
          │                  ↓ 预算还有 → 回到 plan（这就是"循环"）
          │                  ↓ 预算用尽 → partial（带部分结果收尾）
          └── 给结论   → END
```

为什么用状态图而不是手写循环：**循环的出口条件从一个 for 循环的边界，变成了图上可画的边**。
预算、无候选、模型失败这些分支各是一条边，加一条策略就是加一个节点，不用去改循环内部的判定顺序；
每个节点的输入输出都是 state 的一个字段，排查时可以逐个节点看状态怎么变。

    工具、权限、审计、降级这些行为都在自己手里：工具用 @tool 定义但执行走 `tools.run_tool`，
    所以框架只负责图怎么跑，业务约束一条都没交出去。

短期记忆用 LangGraph 的 **checkpointer**（`InMemorySaver`）实现：编译图时挂上它，
每轮按 `thread_id`（就是会话 ID）恢复上一次的状态，节点的执行结果自动存回检查点。
两处配套的设计：

1. **每轮重写消息列表**：`prepare` 用 `RemoveMessage(REMOVE_ALL_MESSAGES)` 清掉旧列表，
   再按「系统提示词 → 检查点里的历史消息 → 本轮问题」的顺序重建。这样系统提示词里的技能正文
   每轮都能按当前话题刷新，而历史（含工具调用与工具返回）来自检查点，不用自己存；
2. **裁剪落在状态上**：重建时用 `trim_messages` 按字符预算取最近若干轮，多出来的消息
   连同 `REMOVE_ALL_MESSAGES` 一起丢掉，所以检查点不会无限增长。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langchain_core.messages.utils import trim_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from langgraph.runtime import Runtime
from sqlalchemy.orm import Session

from app.ai import tools
from app.ai.agent import (
    BASE_SYSTEM_PROMPT,
    MULTI_TURN_PROMPT,
    _normalize_history,
    _skill_source,
    _step_summary,
    _tool_message_content,
    build_diagnose_tool,
)
from app.ai.llm import LLMError, ToolCallingClient
from app.ai.skills.loader import full_context_size, load_skills, render_context, select_skill, skill_index
from app.models.user import User

logger = logging.getLogger(__name__)

# 消息裁剪的预算：用字符数近似 token（中文一字≈一 token 量级），够表达"别把历史无限带进去"
MESSAGE_CHAR_BUDGET = 6000


class AskState(TypedDict, total=False):
    """图的状态：每个节点只读写自己负责的字段。"""

    question: str
    # 请求体带来的历史（只在检查点里还没有上下文时用作种子）
    history: list[tuple[str, str | None]]
    # add_messages reducer：节点返回的消息对象按顺序并入；整个列表由 prepare 按窗口重写
    messages: Annotated[list[AnyMessage], add_messages]
    skill: str | None
    context_chars: dict[str, int]
    history_turns: int
    pending: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    used_tools: list[str]
    budget_left: int
    answer: str | None
    reason: str | None
    degraded: bool


@dataclass
class AskContext:
    """一次问答的运行上下文：数据库会话、调用者、模型、工具清单。

    放在 LangGraph 的 `context` 里而不是 state 里：state 是"这次问答的过程数据"，
    这些是"运行环境"，两者混在一起会让状态难以阅读。
    """

    db: Session
    user: User
    permissions: frozenset[str]
    llm: ToolCallingClient
    client_ip: str | None
    registry: dict[str, tools.ToolSpec]
    # 交给模型的工具对象（LangChain 工具，schema 由 ToolSpec 转换而来）
    tools: list[BaseTool]
    max_steps: int


def _prepare(state: AskState, runtime: Runtime[AskContext]) -> dict[str, Any]:
    """节点：选技能、拼系统提示词、按检查点重建消息窗口，并重置本轮预算。"""
    question = state["question"]
    # 检查点里的历史（含工具调用与工具返回）；线程新建时用请求体带来的历史做种子
    prior = [
        item for item in state.get("messages") or [] if not isinstance(item, SystemMessage)
    ]
    for past_question, past_answer in ([] if prior else state.get("history") or []):
        prior.append(HumanMessage(past_question))
        if past_answer:
            prior.append(AIMessage(past_answer))

    # 技能继承看最近两轮用户提问：追问句本身没有触发词，只看本轮会丢掉技能上下文
    recent_questions = [str(item.content) for item in prior if isinstance(item, HumanMessage)][-2:]
    asked_before = len([item for item in prior if isinstance(item, HumanMessage)])
    prior_chars = sum(len(str(item.content or "")) for item in prior)

    skills = load_skills()
    index_text = skill_index(skills)
    skill = select_skill(" ".join([*recent_questions, question]), skills)
    skill_context = render_context(skill)

    prompt = BASE_SYSTEM_PROMPT
    if prior:
        prompt += MULTI_TURN_PROMPT
    if index_text:
        prompt += f"\n\n可用技能（命中才展开正文）：\n{index_text}"
    if skill_context:
        prompt += f"\n\n{skill_context}"

    # 先拼完整列表再裁剪：system 常驻、从 user 消息开始，避免裁出以 assistant/tool 开头的非法序列
    window = trim_messages(
        [SystemMessage(prompt), *prior, HumanMessage(question)],
        max_tokens=MESSAGE_CHAR_BUDGET,
        token_counter=lambda items: sum(len(str(item.content or "")) for item in items),
        strategy="last",
        include_system=True,
        start_on="human",
    )

    return {
        # 整段重写：清掉检查点里的旧列表，再放回裁剪后的窗口，检查点因此不会无限增长
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *window],
        "skill": skill.name if skill else None,
        "budget_left": runtime.context.max_steps,
        "context_chars": {
            "system_prompt": len(prompt),
            "skill_index": len(index_text),
            "all_skills_full": full_context_size(skills),
            "history": prior_chars,
        },
        "history_turns": asked_before,
        "steps": [],
        "used_tools": [],
        "pending": [],
        "answer": None,
        "degraded": False,
        "reason": None,
    }


def _plan(state: AskState, runtime: Runtime[AskContext]) -> dict[str, Any]:
    """节点：让模型决定下一步——调工具，还是给出结论。"""
    llm = runtime.context.llm
    messages = list(state.get("messages") or [])
    try:
        # 客户端收发的是 OpenAI 协议的字典，消息对象在这里转一次，图内部始终用消息对象
        turn = llm.complete_with_tools(
            messages=messages, tools=runtime.context.tools
        )
    except LLMError as exc:
        logger.warning("数据问答失败：%s", exc)
        return {
            "degraded": True,
            "reason": f"大模型不可用（{exc}）",
            "pending": [],
            "answer": None,
        }

    if not turn.tool_calls:
        return {
            "answer": turn.content,
            # 结论也要进消息列表：检查点存的是一段完整对话，下一轮靠它才看得到上一轮的回答
            "messages": [AIMessage(content=turn.content)] if turn.content else [],
            "pending": [],
            "reason": None if turn.content else "模型没有给出回答",
        }

    return {
        # AIMessage 自带 tool_calls 结构，不用再手拼 assistant 消息字典
        "messages": [
            AIMessage(
                content=turn.content or "",
                tool_calls=[
                    {"name": call.name, "args": call.arguments, "id": call.id}
                    for call in turn.tool_calls
                ],
            )
        ],
        "answer": None,
        "pending": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in turn.tool_calls
        ],
    }


def _execute_tools(state: AskState, runtime: Runtime[AskContext]) -> dict[str, Any]:
    """节点：执行本轮的每个工具调用，把结果作为 tool 消息回灌，并扣一次预算。"""
    ctx = tools.ToolContext(
        db=runtime.context.db,
        user=runtime.context.user,
        permissions=runtime.context.permissions,
        client_ip=runtime.context.client_ip,
    )
    steps = list(state.get("steps") or [])
    used = list(state.get("used_tools") or [])
    budget = state.get("budget_left", 0)
    pending = state.get("pending") or []
    new_messages: list[AnyMessage] = []

    for call in pending:
        result = tools.run_tool(
            ctx, call["name"], call["arguments"], registry=runtime.context.registry
        )
        steps.append(
            {
                "step": runtime.context.max_steps - budget + 1,
                "tool": call["name"],
                "arguments": call["arguments"],
                "ok": result.get("ok", True),
                "summary": _step_summary(result),
                "elapsed_ms": result.get("elapsed_ms", 0),
            }
        )
        if call["name"] not in used:
            used.append(call["name"])
        new_messages.append(
            ToolMessage(
                content=_tool_message_content(result),
                tool_call_id=call["id"],
                name=call["name"],
            )
        )

    return {
        "messages": new_messages,
        "steps": steps,
        "used_tools": used,
        "pending": [],
        "budget_left": max(budget - 1, 0),
    }


def _partial(state: AskState, runtime: Runtime[AskContext]) -> dict[str, Any]:
    """节点：预算用尽——带着已获得的数据收尾，而不是硬编一个答案。"""
    return {
        "degraded": True,
        "answer": None,
        "reason": f"达到工具调用步数上限（{runtime.context.max_steps}），以下为已获得的数据",
    }


def _route_after_plan(state: AskState) -> str:
    """条件边：有工具要调就去执行，否则（给了结论或失败了）结束。"""
    if state.get("degraded"):
        return END
    return "execute_tools" if state.get("pending") else END


def _route_after_tools(state: AskState) -> str:
    """条件边：预算还有就回到 plan，用尽则走收尾分支。"""
    return "plan" if state.get("budget_left", 0) > 0 else "partial"


_CHECKPOINTER: InMemorySaver | None = None
_GRAPH: Any | None = None


def get_checkpointer() -> InMemorySaver:
    """进程内的检查点存储：按 thread_id 保存每轮图状态（短期会话记忆的实体）。"""
    global _CHECKPOINTER
    if _CHECKPOINTER is None:
        _CHECKPOINTER = InMemorySaver()
    return _CHECKPOINTER


def reset_checkpointer() -> None:
    """丢掉全部检查点并让图重新编译。

    只给测试与"清空所有会话"用：换掉实例后必须重新编译，否则图还挂在旧的检查点上。
    """
    global _CHECKPOINTER, _GRAPH
    _CHECKPOINTER = InMemorySaver()
    _GRAPH = None


def thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def prior_context(thread_id: str | None) -> tuple[int, int]:
    """读检查点里已有的上下文：返回（历史轮数, 历史字符数）。没有线程或没有记录就是 (0, 0)。"""
    if not thread_id:
        return (0, 0)
    snapshot = get_graph().get_state(thread_config(thread_id))
    messages = (snapshot.values or {}).get("messages") or []
    turns = sum(1 for item in messages if isinstance(item, HumanMessage))
    chars = sum(
        len(str(item.content or "")) for item in messages if not isinstance(item, SystemMessage)
    )
    return (turns, chars)


def build_graph() -> Any:
    """编译状态图（进程内只编译一次），挂上检查点存储。"""
    builder = StateGraph(AskState, context_schema=AskContext)
    builder.add_node("prepare", _prepare)
    builder.add_node("plan", _plan)
    builder.add_node("execute_tools", _execute_tools)
    builder.add_node("partial", _partial)

    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "plan")
    builder.add_conditional_edges(
        "plan", _route_after_plan, {"execute_tools": "execute_tools", END: END}
    )
    builder.add_conditional_edges(
        "execute_tools", _route_after_tools, {"plan": "plan", "partial": "partial"}
    )
    builder.add_edge("partial", END)
    return builder.compile(checkpointer=get_checkpointer())


def get_graph() -> Any:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run(
    db: Session,
    *,
    question: str,
    user: User,
    permissions: frozenset[str],
    llm: ToolCallingClient,
    client_ip: str | None = None,
    max_steps: int = 5,
    history: Any = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """跑一遍状态图，返回接口层需要的响应结构。

    `thread_id` 就是会话 ID：传了它，这一轮的图状态会存进检查点，下一轮能接着用；
    没传（例如直接调用的单元测试）就开一个临时线程，跑完删掉——不留记忆，也不留垃圾。
    """
    started = time.perf_counter()
    turns = _normalize_history(history)
    prior_turns, prior_chars = prior_context(thread_id)
    ephemeral = thread_id is None
    thread_id = thread_id or f"ephemeral-{uuid4().hex}"

    available = tools.tools_for(permissions)
    if "fault.view" in permissions:
        available.append(build_diagnose_tool(llm))
    if not available:
        return {
            "answer": None,
            "skill": None,
            "steps": [],
            "used_tools": [],
            "degraded": False,
            "reason": "当前账号没有可用的数据查询权限",
            "model": getattr(llm, "model", None),
            "elapsed_ms": 0,
            "history_turns": prior_turns or len(turns),
            "context_chars": {
                "system_prompt": 0,
                "skill_index": 0,
                "all_skills_full": 0,
                "history": prior_chars,
            },
        }
    registry = {item.name: item for item in available}
    tool_context = tools.ToolContext(
        db=db, user=user, permissions=permissions, client_ip=client_ip
    )

    context = AskContext(
        db=db,
        user=user,
        permissions=permissions,
        llm=llm,
        client_ip=client_ip,
        registry=registry,
        tools=tools.as_langchain_tools(available, tool_context),
        max_steps=max_steps,
    )

    try:
        final = get_graph().invoke(
            {"question": question, "history": turns},
            context=context,
            # recursion_limit 关掉递归上限告警：步数由 budget_left 自己控制，图深度是有界的
            config={**thread_config(thread_id), "recursion_limit": (max_steps + 2) * 3},
        )
    finally:
        if ephemeral:
            # 单问单答不留检查点，否则进程里会攒下一堆一次性的线程
            get_checkpointer().delete_thread(thread_id)

    return {
        "answer": final.get("answer"),
        "skill": final.get("skill"),
        "steps": final.get("steps") or [],
        "used_tools": final.get("used_tools") or [],
        "degraded": bool(final.get("degraded")),
        "reason": final.get("reason"),
        "model": getattr(llm, "model", None),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "history_turns": final.get("history_turns", prior_turns or len(turns)),
        "context_chars": final.get("context_chars")
        or {"system_prompt": 0, "skill_index": 0, "all_skills_full": 0, "history": 0},
    }
