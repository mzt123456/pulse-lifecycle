"""相关性重排用例：同词异义要被挡下，重排出错要放行而不是让诊断失败。"""

from typing import Any

import pytest

from app.ai.document import CaseDocument
from app.ai.llm import LLMError
from app.ai.retriever import SearchHit
from app.ai.rerank import LLMReranker


class ScriptedRerankerLLM:
    """只实现 complete_json 的假模型：按脚本返回打分表或抛错。"""

    model = "fake-rerank-model"

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.prompts: list[str] = []

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        self.prompts.append(user)
        if self.error is not None:
            raise self.error
        return self.payload


def _hit(doc_id: str, title: str, cause: str = "密封圈老化") -> SearchHit:
    document = CaseDocument(
        source="synthetic",
        doc_id=doc_id,
        title=title,
        text=f"【现象】{title}  【原因】{cause}",
        payload={"cause": cause},
    )
    return SearchHit(document=document, score=3.0, matched_terms=("软件",))


def test_rerank_drops_word_collision_candidate() -> None:
    """字面撞词但语义无关的候选应当被丢掉——这正是无结果准确率卡在 90% 的原因。"""
    llm = ScriptedRerankerLLM({"relevant": []})  # 一个都不相关
    reranker = LLMReranker(llm, min_score=5)

    outcome = reranker.rerank(
        description="如何申请软件著作权登记",
        hits=[_hit("fault:7", "地面软件提示通讯超时", "通讯线缆断芯")],
    )

    assert outcome.applied is True
    assert outcome.degraded is False
    assert outcome.hits == ()


def test_rerank_keeps_relevant_and_drops_low_scores() -> None:
    llm = ScriptedRerankerLLM(
        {
            "relevant": [
                {"id": "C1", "score": 9, "reason": "现象一致"},
                {"id": "C2", "score": 3, "reason": "只是同类"},
            ]
        }
    )
    reranker = LLMReranker(llm, min_score=5)

    outcome = reranker.rerank(
        description="下井后压力保持不住",
        hits=[_hit("a", "密封面渗漏"), _hit("b", "电池电压下降")],
    )

    assert [hit.document.doc_id for hit in outcome.hits] == ["a"]
    assert outcome.scores == {"a": 9, "b": 3}
    assert outcome.reasons["b"] == "只是同类"


def test_rerank_fails_open_when_model_errors() -> None:
    """重排失败必须放行：它是精度优化，不该让整个诊断不可用。"""
    reranker = LLMReranker(ScriptedRerankerLLM(error=LLMError("超时")), min_score=5)
    hits = [_hit("a", "密封面渗漏")]

    outcome = reranker.rerank(description="压力保持不住", hits=hits)

    assert outcome.hits == tuple(hits)
    assert outcome.degraded is True


def test_rerank_fails_open_when_payload_is_not_a_list() -> None:
    reranker = LLMReranker(ScriptedRerankerLLM({"answer": "不知道"}), min_score=5)
    hits = [_hit("a", "密封面渗漏")]

    outcome = reranker.rerank(description="压力保持不住", hits=hits)

    assert outcome.hits == tuple(hits)
    assert outcome.degraded is True


def test_rerank_ignores_out_of_range_and_bad_ids() -> None:
    llm = ScriptedRerankerLLM(
        {
            "relevant": [
                {"id": "C9", "score": 10},          # 超出候选范围
                {"id": "abc", "score": 10},         # 非法编号
                {"id": "C1", "score": "高中"},      # 分数不是数字
                {"id": "C1", "score": 6},           # 有效
            ]
        }
    )
    reranker = LLMReranker(llm, min_score=5)

    outcome = reranker.rerank(description="压力保持不住", hits=[_hit("a", "密封面渗漏")])

    assert [hit.document.doc_id for hit in outcome.hits] == ["a"]
    assert outcome.scores == {"a": 6}


def test_rerank_without_candidates_is_a_noop() -> None:
    llm = ScriptedRerankerLLM({"relevant": []})
    outcome = LLMReranker(llm, min_score=5).rerank(description="压力保持不住", hits=[])

    assert outcome.hits == ()
    assert outcome.applied is False
    assert llm.prompts == []
