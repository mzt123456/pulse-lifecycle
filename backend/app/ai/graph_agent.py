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

工具、权限、审计、降级这些行为与手写循环完全一致——两套实现共用 `tools.py`，
所以换编排方式不会改变对外行为，`orchestrator` 字段会记录本次实际用的是哪一套。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import convert_to_openai_messages, trim_messages
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
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
    history: list[tuple[str, str | None]]
    # add_messages：节点只返回"新增的消息"，由 reducer 负责追加，不用自己拼列表
    messages: Annotated[list[AnyMessage], add_messages]
    skill: str | None
    context_chars: dict[str, int]
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
    schemas: list[dict[str, Any]]
    max_steps: int


def _prepare(state: AskState, runtime: Runtime[AskContext]) -> dict[str, Any]:
    """节点：选技能、拼系统提示词、准备消息历史与预算。"""
    question = state["question"]
    turns = state.get("history") or []
    skills = load_skills()
    index_text = skill_index(skills)
    skill = select_skill(_skill_source(question, turns), skills)
    skill_context = render_context(skill)

    prompt = BASE_SYSTEM_PROMPT
    if turns:
        prompt += MULTI_TURN_PROMPT
    if index_text:
        prompt += f"\n\n可用技能（命中才展开正文）：\n{index_text}"
    if skill_context:
        prompt += f"\n\n{skill_context}"

    messages: list[AnyMessage] = [SystemMessage(prompt)]
    for past_question, past_answer in turns:
        messages.append(HumanMessage(past_question))
        if past_answer:
            messages.append(AIMessage(past_answer))
    messages.append(HumanMessage(question))

    # 历史裁剪交给框架：按字符预算保留最近若干轮，system 常驻、从 user 消息开始，
    # 避免裁出以 assistant/tool 开头的非法序列
    messages = trim_messages(
        messages,
        max_tokens=MESSAGE_CHAR_BUDGET,
        token_counter=lambda items: sum(len(str(item.content or "")) for item in items),
        strategy="last",
        include_system=True,
        start_on="human",
    )

    return {
        "messages": messages,
        "skill": skill.name if skill else None,
        "budget_left": runtime.context.max_steps,
        "context_chars": {
            "system_prompt": len(prompt),
            "skill_index": len(index_text),
            "all_skills_full": full_context_size(skills),
            "history": sum(len(item[0]) + len(item[1] or "") for item in turns),
        },
        "steps": [],
        "used_tools": [],
        "pending": [],
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
            messages=convert_to_openai_messages(messages), tools=runtime.context.schemas
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


def build_graph() -> Any:
    """编译状态图（进程内只编译一次）。"""
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
    return builder.compile()


_GRAPH: Any | None = None


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
) -> dict[str, Any]:
    """跑一遍状态图，返回与手写循环一致的响应结构。"""
    started = time.perf_counter()
    turns = _normalize_history(history)

    available = tools.tools_for(permissions)
    if "fault.view" in permissions:
        available.append(build_diagnose_tool(llm))
    registry = {item.name: item for item in available}

    context = AskContext(
        db=db,
        user=user,
        permissions=permissions,
        llm=llm,
        client_ip=client_ip,
        registry=registry,
        schemas=[item.schema for item in available],
        max_steps=max_steps,
    )

    final = get_graph().invoke(
        {"question": question, "history": turns},
        context=context,
        # 关掉递归上限告警：步数由 budget_left 自己控制，图深度是有界的
        config={"recursion_limit": (max_steps + 2) * 3},
    )

    return {
        "answer": final.get("answer"),
        "skill": final.get("skill"),
        "steps": final.get("steps") or [],
        "used_tools": final.get("used_tools") or [],
        "degraded": bool(final.get("degraded")),
        "reason": final.get("reason"),
        "model": getattr(llm, "model", None),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "history_turns": len(turns),
        "context_chars": final.get("context_chars")
        or {"system_prompt": 0, "skill_index": 0, "all_skills_full": 0, "history": 0},
        "orchestrator": "langgraph",
    }
