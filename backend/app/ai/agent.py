"""Agent 循环：让模型自己决定调哪些工具、调几次，最后组织答案。

循环是手写的，不是套框架：

```
把问题与工具清单交给模型
  ↓ 模型要求调用工具（可能一次多个）
执行工具 → 结果回灌 → 再交给模型
  ↓ 模型认为信息够了
输出最终答案
```

几条边界，都是有意的：

- **不暴露无权限的工具**：用户看不到的数据，模型连尝试的入口都没有；
- **步数有上限**：超过就带着已获得的结果收尾，绝不无限循环烧额度；
- **工具失败不中断**：把结构化错误交回模型，让它如实告诉用户；
- **技能按需展开**：常驻提示词里只有技能索引，命中哪个才展开正文与参考资料。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.ai import diagnosis, tools
from app.ai.llm import LLMError, ToolCallingClient
from app.ai.skills.loader import (
    full_context_size,
    load_skills,
    render_context,
    select_skill,
    skill_index,
)
from app.models.user import User

logger = logging.getLogger(__name__)

MAX_STEPS = 5
MAX_TOOL_RESULT_CHARS = 4000
# 多轮对话只带最近几轮，且只带问答正文：工具调用细节不回灌，
# 一是省上下文，二是历史里的数据可能已经变了，不该被当成当前事实。
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 1500

BASE_SYSTEM_PROMPT = """你是剪切阀脉冲器全生命周期管理系统的运维助手，服务对象是维保与管理人员。

工作方式：
- 需要业务数据时必须调用工具获取，不要凭印象回答，也不要根据字段名猜数据；
- 同一轮可以调用多个工具，但不要重复调用参数相同的工具；
- 工具返回为空或失败时如实说明，不要用通用经验补足；
- 回答用中文，先给结论再给依据，数字带单位与范围。

你没有把握时，宁可说明缺少什么信息，也不要给一个看起来完整的答案。"""

MULTI_TURN_PROMPT = """

这是多轮对话。历史消息只包含之前问答的正文，其中的数据可能已经过时：
只要问题涉及具体数据（库存、工单、设备状态、故障记录），就必须重新调用工具取当前值，
不要直接引用历史里的数字。"""


def build_diagnose_tool(llm: Any) -> tools.ToolSpec:
    """把故障诊断（RAG）也做成一个工具，与数据查询工具并列。

    诊断工具需要模型客户端，所以在这里按调用注入，而不是写进全局注册表。
    """

    def handler(ctx: tools.ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        equipment_no = tools._text(arguments.get("equipment_no"))
        equipment_id = tools.resolve_equipment_id(ctx, equipment_no)
        if equipment_no and equipment_id is None:
            return {"found": False, "note": f"没有找到编号为 {equipment_no} 的设备", "causes": []}

        result = diagnosis.diagnose(
            ctx.db,
            description=tools._text(arguments.get("description"), max_length=500) or "",
            fault_type=tools._text(arguments.get("fault_type")),
            equipment_id=equipment_id,
            top_k=min(tools._limit(arguments.get("top_k")), 5),
            llm=llm,
        )
        return {
            "found": result["found"],
            "degraded": result["degraded"],
            "confidence": result["confidence"],
            "causes": result["causes"],
            "actions": result["actions"],
            "citations": result["citations"],
            "note": result["note"],
            "matches": [
                {
                    "doc_id": item["doc_id"],
                    "title": item["title"],
                    "source_label": item["source_label"],
                    "score": item["score"],
                    "equipment_no": item["equipment_no"],
                }
                for item in result["matches"][:5]
            ],
        }

    return tools.ToolSpec(
        name="diagnose_fault",
        description="故障案例检索与归因：输入故障现象，返回可能原因、建议处置与引用到的案例，"
        "并标注是否为降级结果（未经过模型归纳）。",
        permission="fault.view",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "故障现象，用现场的话描述即可"},
                "equipment_no": {"type": "string", "description": "脉冲编号，可选"},
                "fault_type": {"type": "string", "description": "故障类型，取值来自字典"},
                "top_k": {"type": "integer", "description": "检索案例条数，默认 5"},
            },
            "required": ["description"],
        },
        handler=handler,
    )


def _tool_message_content(result: dict[str, Any]) -> str:
    """工具结果回灌给模型前的截断保护，避免单次返回撑爆上下文。"""
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "…（结果已截断，如需更多请缩小查询范围）"
    return text


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _step_summary(result: dict[str, Any]) -> str:
    if not result.get("ok", True):
        return f"失败：{result.get('error')}"
    if isinstance(result.get("items"), list):
        return f"返回 {len(result['items'])} 条（共 {result.get('total', len(result['items']))} 条）"
    if result.get("found") is False:
        return "未找到匹配结果"
    return "查询完成"


def _assistant_message(content: str | None, calls: tuple[Any, ...]) -> dict[str, Any]:
    """按 OpenAI 协议回填 assistant 消息，tool_calls 必须原样带回。"""
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False, default=str),
                },
            }
            for call in calls
        ],
    }


def _normalize_history(history: Any) -> list[tuple[str, str | None]]:
    """整理历史轮次：只保留最近若干轮，截断过长内容，丢掉空问题。"""
    if not isinstance(history, (list, tuple)):
        return []

    turns: list[tuple[str, str | None]] = []
    for item in history:
        if isinstance(item, dict):
            question = item.get("question")
            answer = item.get("answer")
        else:
            continue
        text = str(question or "").strip()
        if not text:
            continue
        answer_text = str(answer).strip() if answer else None
        turns.append((text[:MAX_HISTORY_CHARS], answer_text[:MAX_HISTORY_CHARS] if answer_text else None))
    return turns[-MAX_HISTORY_TURNS:]


def _skill_source(question: str, history: list[tuple[str, str | None]]) -> str:
    """技能选择看最近两轮用户提问 + 本轮问题。

    追问常常没有触发词（"那怎么处理""还有吗"），只看本轮会丢掉技能上下文；
    但也不能把全部历史都算进去，否则话题切换后仍套着旧技能。
    """
    recent = [item[0] for item in history[-2:]]
    return " ".join([*recent, question])


def answer(
    db: Session,
    *,
    question: str,
    user: User,
    permissions: frozenset[str],
    llm: ToolCallingClient | None,
    client_ip: str | None = None,
    max_steps: int = MAX_STEPS,
    history: Any = None,
) -> dict[str, Any]:
    """用工具调用回答一个业务问题；history 为之前的问答轮次（可选）。"""
    started = time.perf_counter()
    model_name = getattr(llm, "model", None)
    turns = _normalize_history(history)

    skills = load_skills()
    index_text = skill_index(skills)
    skill = select_skill(_skill_source(question, turns), skills)
    skill_context = render_context(skill)
    system_prompt = BASE_SYSTEM_PROMPT
    if turns:
        system_prompt += MULTI_TURN_PROMPT
    if index_text:
        system_prompt += f"\n\n可用技能（命中才展开正文）：\n{index_text}"
    if skill_context:
        system_prompt += f"\n\n{skill_context}"

    result: dict[str, Any] = {
        "answer": None,
        "skill": skill.name if skill else None,
        "steps": [],
        "used_tools": [],
        "degraded": False,
        "reason": None,
        "model": model_name,
        "elapsed_ms": 0,
        "history_turns": len(turns),
        "context_chars": {
            "system_prompt": len(system_prompt),
            "skill_index": len(index_text),
            "all_skills_full": full_context_size(skills),
            "history": sum(len(item[0]) + len(item[1] or "") for item in turns),
        },
    }

    if llm is None:
        result.update(
            degraded=True,
            reason="未配置大模型 API Key，无法进行数据问答",
            elapsed_ms=_elapsed_ms(started),
        )
        return result

    available = tools.tools_for(permissions)
    if "fault.view" in permissions:
        available.append(build_diagnose_tool(llm))
    if not available:
        result.update(reason="当前账号没有可用的数据查询权限", elapsed_ms=_elapsed_ms(started))
        return result

    ctx = tools.ToolContext(db=db, user=user, permissions=permissions, client_ip=client_ip)
    schemas = [item.schema for item in available]
    # 本轮可用的工具表：含按需注入的诊断工具，run_tool 按它查找
    registry = {item.name: item for item in available}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    for past_question, past_answer in turns:
        messages.append({"role": "user", "content": past_question})
        # 只有回答过（非降级）的轮次才作为 assistant 消息回灌
        if past_answer:
            messages.append({"role": "assistant", "content": past_answer})
    messages.append({"role": "user", "content": question})

    for step in range(1, max_steps + 1):
        try:
            turn = llm.complete_with_tools(messages=messages, tools=schemas)
        except LLMError as exc:
            logger.warning("数据问答失败：%s", exc)
            result.update(
                degraded=True,
                reason=f"大模型不可用（{exc}）",
                elapsed_ms=_elapsed_ms(started),
            )
            return result

        if not turn.tool_calls:
            result["answer"] = turn.content
            result["elapsed_ms"] = _elapsed_ms(started)
            if not turn.content:
                result["reason"] = "模型没有给出回答"
            return result

        messages.append(_assistant_message(turn.content, turn.tool_calls))
        for call in turn.tool_calls:
            tool_result = tools.run_tool(ctx, call.name, call.arguments, registry=registry)
            result["steps"].append(
                {
                    "step": step,
                    "tool": call.name,
                    "arguments": call.arguments,
                    "ok": tool_result.get("ok", True),
                    "summary": _step_summary(tool_result),
                    "elapsed_ms": tool_result.get("elapsed_ms", 0),
                }
            )
            if call.name not in result["used_tools"]:
                result["used_tools"].append(call.name)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": _tool_message_content(tool_result),
                }
            )

    # 步数用尽：把已获得的中间结果如实交回，而不是硬编一个答案
    result.update(
        degraded=True,
        reason=f"达到工具调用步数上限（{max_steps}），以下为已获得的数据",
        elapsed_ms=_elapsed_ms(started),
    )
    return result
