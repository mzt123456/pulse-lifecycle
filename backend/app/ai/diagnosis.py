"""故障案例智能诊断：结构化预过滤 → BM25 检索 → 大模型生成 → 引用校验。

两条硬约束，都是「抗幻觉」的一部分：

1. 检索为空时不调用大模型，直接回答「未找到相似案例」——语料里没有的东西，
   让模型自由发挥只会得到编造的原因；
2. 大模型不可用（未配置 Key、超时、返回不合法）时降级为「只返回相似案例」，
   检索链路本身不依赖模型，接口和前端都还能用。

模型给出的引用会与本次检索到的案例逐一核对，对不上的引用一律丢弃；
一条引用都不剩时，置信度强制降为「低」。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.ai.llm import ChatClient, LLMError
from app.ai.prompts import SYSTEM_PROMPT, build_cases_block, build_diagnosis_prompt
from app.ai.retriever import SearchHit, search_with_fallback
from app.ai.index_store import get_corpus_index
from app.services import equipment as equipment_service

logger = logging.getLogger(__name__)

MAX_ITEMS = 5
CONFIDENCE_LEVELS = ("高", "中", "低")
DEGRADED_NOTE = "当前结果为相似案例检索，未经过大模型归纳；请人工判断后使用。"


def _payload(hit: SearchHit, key: str) -> Any:
    return hit.document.payload.get(key)


def _serialize_match(hit: SearchHit, alias: str) -> dict[str, Any]:
    return {
        "alias": alias,
        "doc_id": hit.document.doc_id,
        "source": hit.document.source,
        "source_label": hit.document.source_label,
        "title": hit.document.title,
        "score": round(hit.score, 3),
        "matched_terms": list(hit.matched_terms),
        "record_id": _payload(hit, "record_id"),
        "equipment_no": _payload(hit, "equipment_no"),
        "fault_type": _payload(hit, "fault_type"),
        "cause": _payload(hit, "cause"),
        "solution": _payload(hit, "solution"),
    }


def _collect(hits: Sequence[SearchHit], key: str) -> list[dict[str, Any]]:
    """汇总案例里的原因/处置，去重并保留来源案例 ID（降级路径直接回显这些）。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        text = (_payload(hit, key) or "").strip() if isinstance(_payload(hit, key), str) else ""
        if not text or text in seen:
            continue
        seen.add(text)
        items.append({"text": text, "case_ids": [hit.document.doc_id]})
        if len(items) >= MAX_ITEMS:
            break
    return items


def _normalize_items(raw: Any, case_map: dict[str, str]) -> list[dict[str, Any]]:
    """把模型返回的原因/处置列表收敛成固定结构，并核对引用。"""
    known_doc_ids = {doc_id for doc_id in case_map.values()}
    items: list[dict[str, Any]] = []

    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, str):
            text, raw_ids = entry, []
        elif isinstance(entry, dict):
            text = entry.get("text") or entry.get("reason") or entry.get("action") or ""
            raw_ids = entry.get("case_ids") or entry.get("citations") or []
        else:
            continue

        text = str(text).strip()[:200]
        if not text:
            continue

        cited: list[str] = []
        for value in raw_ids if isinstance(raw_ids, list) else []:
            key = str(value).strip()
            # 模型可能返回编号（C1）也可能直接返回文档 ID，两种都接受
            doc_id = case_map.get(key) or (key if key in known_doc_ids else None)
            if doc_id and doc_id not in cited:
                cited.append(doc_id)

        items.append({"text": text, "case_ids": cited})
        if len(items) >= MAX_ITEMS:
            break

    return items


def _base_result(
    *,
    found: bool,
    degraded: bool,
    reason: str | None,
    matches: list[dict[str, Any]],
    elapsed_ms: int,
    filter_relaxed: bool,
    model: str | None,
) -> dict[str, Any]:
    return {
        "found": found,
        "degraded": degraded,
        "reason": reason,
        "causes": [],
        "actions": [],
        "confidence": None,
        "note": None,
        "citations": [],
        "matches": matches,
        "model": model,
        "elapsed_ms": elapsed_ms,
        "filter_relaxed": filter_relaxed,
    }


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def diagnose(
    db: Session,
    *,
    description: str,
    fault_type: str | None = None,
    instrument_type: str | None = None,
    equipment_id: int | None = None,
    top_k: int = 5,
    include_synthetic: bool = True,
    llm: ChatClient | None = None,
) -> dict[str, Any]:
    """给一段故障现象，返回可能原因、建议处置与引用案例。"""
    started = time.perf_counter()
    equipment_no: str | None = None

    if equipment_id is not None:
        equipment = equipment_service.get_equipment(db, equipment_id)
        equipment_no = equipment.equipment_no
        if not instrument_type and equipment.model:
            instrument_type = equipment.model

    index = get_corpus_index(db, include_synthetic=include_synthetic)
    filters = {
        key: value
        for key, value in (("fault_type", fault_type), ("instrument_type", instrument_type))
        if value
    }
    outcome = search_with_fallback(index, description, top_k=top_k, filters=filters or None)

    case_map: dict[str, str] = {}
    matches: list[dict[str, Any]] = []
    cases_block = ""
    if outcome.hits:
        # build_cases_block 只渲染前 8 条，位置索引与 hits 前若干项一一对应
        cases_block, case_map = build_cases_block(outcome.hits)
        matches = [
            _serialize_match(outcome.hits[position], alias)
            for position, alias in enumerate(case_map)
        ]

    model_name = getattr(llm, "model", None)

    # 检索为空：不调用模型，明确回答「未找到」，这是抗幻觉的第一道闸门
    if not outcome.hits:
        return _base_result(
            found=False,
            degraded=False,
            reason="语料中没有与现象描述匹配的案例",
            matches=[],
            elapsed_ms=_elapsed_ms(started),
            filter_relaxed=False,
            model=model_name,
        )

    # 未配置模型或调用失败：降级为相似案例列表
    if llm is None:
        result = _base_result(
            found=True,
            degraded=True,
            reason="未配置大模型 API Key，已降级为相似案例检索",
            matches=matches,
            elapsed_ms=_elapsed_ms(started),
            filter_relaxed=outcome.relaxed,
            model=None,
        )
        result["causes"] = _collect(outcome.hits, "cause")
        result["actions"] = _collect(outcome.hits, "solution")
        result["confidence"] = "低"
        result["note"] = DEGRADED_NOTE
        return result

    prompt = build_diagnosis_prompt(
        description=description,
        cases_block=cases_block,
        fault_type=fault_type,
        instrument_type=instrument_type,
        equipment_no=equipment_no,
    )

    try:
        raw = llm.complete_json(system=SYSTEM_PROMPT, user=prompt)
    except LLMError as exc:
        logger.warning("诊断降级：%s", exc)
        result = _base_result(
            found=True,
            degraded=True,
            reason=f"大模型不可用（{exc}），已降级为相似案例检索",
            matches=matches,
            elapsed_ms=_elapsed_ms(started),
            filter_relaxed=outcome.relaxed,
            model=model_name,
        )
        result["causes"] = _collect(outcome.hits, "cause")
        result["actions"] = _collect(outcome.hits, "solution")
        result["confidence"] = "低"
        result["note"] = DEGRADED_NOTE
        return result

    causes = _normalize_items(raw.get("causes"), case_map)
    actions = _normalize_items(raw.get("actions"), case_map)
    citations = list(
        dict.fromkeys(
            doc_id for item in [*causes, *actions] for doc_id in item["case_ids"]
        )
    )

    confidence = str(raw.get("confidence") or "").strip()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "低"
    note = str(raw.get("note") or "").strip()[:300] or None

    if (causes or actions) and not citations:
        # 模型给了结论却拿不出可核对的引用：保留内容但明确降级置信度
        confidence = "低"
        note = f"{note} 模型未给出可核对的案例引用。" if note else "模型未给出可核对的案例引用。"

    result = _base_result(
        found=bool(causes or actions),
        degraded=False,
        reason=None if (causes or actions) else "模型未给出可用结论",
        matches=matches,
        elapsed_ms=_elapsed_ms(started),
        filter_relaxed=outcome.relaxed,
        model=model_name,
    )
    result["causes"] = causes
    result["actions"] = actions
    result["confidence"] = confidence
    result["note"] = note
    result["citations"] = citations
    return result
