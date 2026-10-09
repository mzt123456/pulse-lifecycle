"""检索重排：用大模型判断候选案例是否真的在说同一件事。

为什么需要这一层：BM25 只看字面，救不了同词异义。实测里"如何申请软件著作权登记"
会靠"软件"两个字命中"地面软件提示通讯超时"——字面确实撞上了，语义上毫无关系。

为什么用大模型重排而不是向量检索：本项目的模型服务（DeepSeek）只提供对话模型，
没有 embedding 接口；本地跑 BGE 要装 torch 并下载模型，对这套演示环境过重。
大模型重排用的是已经在线的同一个模型，零新增依赖，而且判断标准可以写成业务规则。

可替换性：`Reranker` 是一个协议，将来换成向量检索或专用重排模型（bge-reranker）时，
只需要再写一个实现，诊断流程不用改。重排失败一律**放行**（fail-open），
宁可多带一条候选，也不要因为重排出错让整个诊断不可用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.ai.llm import ChatClient, LLMError
from app.ai.retriever import SearchHit

logger = logging.getLogger(__name__)

DEFAULT_MIN_SCORE = 5

RERANK_SYSTEM_PROMPT = """你是检索结果的相关性裁判，服务对象是井下脉冲器的维保人员。

给你一段现场现象描述，以及若干候选案例。请判断每个候选案例是否**真的在说同一类故障**，
并按 0-10 打分（10 分表示现象几乎一致，5 分表示同类故障但现象有差异，5 分以下表示不相关）。

特别注意：**不要因为撞到同一个词就判为相关**。例如"软件著作权登记"与"地面软件提示通讯超时"，
虽然都含"软件"，但一个说的是著作权手续，一个说的是设备地面软件，属于不相关。

只输出 JSON，不要解释：
{"relevant":[{"id":"C1","score":8,"reason":"一句话理由"}]}
未列出的候选项按不相关处理。
"""


@dataclass(frozen=True)
class RerankOutcome:
    """重排结果：保留下来的命中、是否真的执行过、以及降级标记。"""

    hits: tuple[SearchHit, ...]
    applied: bool
    degraded: bool = False
    scores: dict[str, int] = None  # type: ignore[assignment]
    reasons: dict[str, str] = None  # type: ignore[assignment]
    # 重排自身的 token 用量：单次成本要算上它，否则成本口径就是虚低的
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.scores is None:
            object.__setattr__(self, "scores", {})
        if self.reasons is None:
            object.__setattr__(self, "reasons", {})


class Reranker(Protocol):
    """重排器协议：输入查询与候选，输出保留的候选。"""

    def rerank(self, *, description: str, hits: list[SearchHit]) -> RerankOutcome:
        ...


def _build_prompt(description: str, hits: list[SearchHit]) -> str:
    lines = [f"【现场现象】{description}", "", "【候选案例】"]
    for index, hit in enumerate(hits, start=1):
        lines.append(f"[C{index}] {hit.document.title}")
        # 只给现象与原因，够判断相关性又不浪费 token
        payload = hit.document.payload
        if payload.get("cause"):
            lines.append(f"  原因：{payload['cause']}")
        lines.append(f"  正文：{hit.document.text.splitlines()[-1][:120]}")
    return "\n".join(lines)


class LLMReranker:
    """用对话模型打分并过滤掉不相关的候选。"""

    def __init__(self, llm: ChatClient, *, min_score: int = DEFAULT_MIN_SCORE) -> None:
        self.llm = llm
        self.min_score = min_score

    def rerank(self, *, description: str, hits: list[SearchHit]) -> RerankOutcome:
        if not hits:
            return RerankOutcome(hits=(), applied=False)

        try:
            raw = self.llm.complete_json(
                system=RERANK_SYSTEM_PROMPT,
                user=_build_prompt(description, hits),
            )
        except LLMError as exc:
            # 重排只是精度优化：调用失败就按原顺序放行，不能让诊断整体失败
            logger.warning("重排失败，按原顺序放行：%s", exc)
            return RerankOutcome(
                hits=tuple(hits),
                applied=True,
                degraded=True,
                total_tokens=self._last_tokens(),
            )

        entries = raw.get("relevant")
        if not isinstance(entries, list):
            return RerankOutcome(
                hits=tuple(hits),
                applied=True,
                degraded=True,
                total_tokens=self._last_tokens(),
            )

        scores: dict[str, int] = {}
        reasons: dict[str, str] = {}
        for item in entries:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("id") or "").strip().upper()
            if not alias.startswith("C") or not alias[1:].isdigit():
                continue
            position = int(alias[1:]) - 1
            if not 0 <= position < len(hits):
                continue
            try:
                score = int(item.get("score"))
            except (TypeError, ValueError):
                continue
            doc_id = hits[position].document.doc_id
            scores[doc_id] = score
            reason = item.get("reason")
            if reason:
                reasons[doc_id] = str(reason)[:120]

        kept = [
            hit for hit in hits if scores.get(hit.document.doc_id, 0) >= self.min_score
        ]
        return RerankOutcome(
            hits=tuple(kept),
            applied=True,
            degraded=False,
            scores=scores,
            reasons=reasons,
            total_tokens=self._last_tokens(),
        )

    def _last_tokens(self) -> int:
        usage = getattr(self.llm, "last_usage", None)
        return int(getattr(usage, "total_tokens", 0) or 0)


def build_reranker(llm: ChatClient | None, *, enabled: bool, min_score: int) -> Reranker | None:
    """按配置构造重排器；未开启或没有模型时返回 None。"""
    if not enabled or llm is None:
        return None
    return LLMReranker(llm, min_score=min_score)
