"""数据问答的入口与共享的提示词/工具辅助。

编排本身在 `graph_agent.py`（LangGraph 状态图）：节点、条件边、步数预算与收尾分支都在那里。
这个文件只留三样东西：

1. **入口** `answer()`：没有模型时按降级返回，其余交给图；
2. **提示词**：基础系统提示词与多轮说明（业务规则，框架不提供）；
3. **共享辅助**：诊断工具的定义、工具结果截断、步骤摘要、历史整理——图与测试都用它们。

几条边界是有意的：不暴露无权限的工具（用户看不到的数据，模型连尝试的入口都没有）；
步数有上限、超过就带着已获得的结果收尾；工具失败不中断，把结构化错误交回模型。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.ai import diagnosis, tools
from app.ai.embedding import build_embedder
from app.ai.llm import ToolCallingClient
from app.ai.rerank import build_reranker
from app.core.config import get_settings
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

        settings = get_settings()
        result = diagnosis.diagnose(
            ctx.db,
            description=tools._text(arguments.get("description"), max_length=500) or "",
            fault_type=tools._text(arguments.get("fault_type")),
            equipment_id=equipment_id,
            top_k=min(tools._limit(arguments.get("top_k")), 5),
            llm=llm,
            reranker=build_reranker(
                llm, enabled=settings.ai_rerank, min_score=settings.ai_rerank_min_score
            ),
            embedder=build_embedder(settings),
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


# ----------------------------------------------------------------- 共享辅助


def _tool_message_content(result: dict[str, Any]) -> str:
    """工具结果回灌给模型前的截断保护，避免单次返回撑爆上下文。"""
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "…（结果已截断，如需更多请缩小查询范围）"
    return text


def _step_summary(result: dict[str, Any]) -> str:
    if not result.get("ok", True):
        return f"失败：{result.get('error')}"
    if isinstance(result.get("items"), list):
        return f"返回 {len(result['items'])} 条（共 {result.get('total', len(result['items']))} 条）"
    if result.get("found") is False:
        return "未找到匹配结果"
    return "查询完成"


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


def _degraded_result(reason: str, *, turns: int, chars: int) -> dict[str, Any]:
    """降级返回：只报数，不回内容——调用方负责算好带入了多少轮、多少字。"""
    return {
        "answer": None,
        "skill": None,
        "steps": [],
        "used_tools": [],
        "degraded": True,
        "reason": reason,
        "model": None,
        "elapsed_ms": 0,
        "history_turns": turns,
        "context_chars": {
            "system_prompt": 0,
            "skill_index": 0,
            "all_skills_full": 0,
            "history": chars,
        },
    }


# ----------------------------------------------------------------- 入口


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
    thread_id: str | None = None,
) -> dict[str, Any]:
    """用工具调用回答一个业务问题：编排交给 LangGraph 状态图。

    这里只负责两件框架不该管的事：没有模型时按降级返回（而不是报错）；
    图执行本身出意外时给出降级说明与原因（而不是抛 500）。

    `thread_id` 是会话 ID：编排层用它去检查点里取上一轮的上下文（短期记忆）。
    """
    # 局部导入：graph_agent 依赖本模块的系统提示词与辅助函数，放模块顶层会成环
    from app.ai import graph_agent

    if llm is None:
        # 没有 Key 时不进图，但"带入了多少轮"照样按检查点里的实际上下文报
        turns, chars = graph_agent.prior_context(thread_id)
        if not turns:
            seed = _normalize_history(history)
            turns, chars = len(seed), sum(len(item[0]) + len(item[1] or "") for item in seed)
        return _degraded_result("未配置大模型 API Key，无法进行数据问答", turns=turns, chars=chars)

    # 本轮开始前的上下文规模：图跑挂了也要如实报，而且此时问题可能已经写进检查点了
    before_turns, before_chars = graph_agent.prior_context(thread_id)
    try:
        return graph_agent.run(
            db,
            question=question,
            user=user,
            permissions=permissions,
            llm=llm,
            client_ip=client_ip,
            max_steps=max_steps,
            history=history,
            thread_id=thread_id,
        )
    except Exception:
        logger.exception("图编排执行失败")
        return _degraded_result(
            "编排执行失败，请稍后重试", turns=before_turns, chars=before_chars
        )
