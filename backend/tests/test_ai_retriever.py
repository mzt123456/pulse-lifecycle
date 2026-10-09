"""检索基线用例：分词、BM25 排序、结构化预过滤与结果稳定性。"""

from app.ai.document import CaseDocument
from app.ai.retriever import BM25Index, tokenize


def _doc(doc_id: str, text: str, **payload: object) -> CaseDocument:
    return CaseDocument(
        source="synthetic",
        doc_id=doc_id,
        title=doc_id,
        text=text,
        payload=dict(payload),
    )


def test_tokenize_keeps_model_number_intact() -> None:
    assert "yst-48r" in tokenize("YST-48R 仪器下井后压力异常")


def test_tokenize_drops_stopwords_and_single_characters() -> None:
    assert tokenize("的问题和情况") == []
    assert tokenize(None) == []


def test_bm25_ranks_relevant_document_first() -> None:
    index = BM25Index(
        [
            _doc("a", "【现象】下井后压力异常  【原因】密封圈老化  【处置】更换密封圈"),
            _doc("b", "【现象】地面解码误码率偏高  【原因】脉冲波形畸变  【处置】调整脉冲参数"),
            _doc("c", "【现象】电池电压下降过快  【原因】电池组一致性差  【处置】整组更换电池"),
        ]
    )

    hits = index.search("压力保持不住，密封圈是不是老化了")

    assert hits
    assert hits[0].document.doc_id == "a"
    assert "密封圈" in hits[0].matched_terms


def test_bm25_returns_nothing_when_no_term_matches() -> None:
    index = BM25Index([_doc("a", "【现象】下井后压力异常")])
    assert index.search("转盘转速补偿") == []


def test_empty_or_stopword_only_query_returns_nothing() -> None:
    index = BM25Index([_doc("a", "【现象】下井后压力异常")])
    assert index.search("") == []
    assert index.search("   ") == []
    assert index.search("的问题和情况") == []
    assert index.search("压力", top_k=0) == []


def test_structured_filter_restricts_candidates() -> None:
    index = BM25Index(
        [
            _doc("a", "【现象】压力异常 密封圈老化", fault_type="密封失效"),
            _doc("b", "【现象】压力异常 密封圈老化", fault_type="电气故障"),
        ]
    )

    hits = index.search("压力异常 密封圈老化", filters={"fault_type": "电气故障"})

    assert [hit.document.doc_id for hit in hits] == ["b"]


def test_equal_scores_fall_back_to_doc_id_for_stable_order() -> None:
    index = BM25Index([_doc("b", "密封圈老化"), _doc("a", "密封圈老化")])
    assert [hit.document.doc_id for hit in index.search("密封圈老化")] == ["a", "b"]


def test_index_exposes_document_count() -> None:
    assert len(BM25Index([])) == 0
    assert len(BM25Index([_doc("a", "压力异常")])) == 1


def test_terms_present_in_most_documents_are_ignored_on_large_corpus() -> None:
    """语料够大时，几乎每条都有的词不该成为命中理由。"""
    common = "【现象】压力异常 【原因】密封圈老化"
    documents = [_doc(f"common-{i}", common) for i in range(12)]
    documents.append(_doc("target", "【现象】地面解码误码率偏高 【原因】脉冲波形畸变"))

    index = BM25Index(documents)

    # 「压力」「密封圈」出现在 13 条中的 12 条，超过半数，被判为无区分度词；
    # 查询里只剩这类词时返回空，而不是把 12 条重复案例都倒出来
    assert index.search("现象") == []
    assert index.search("压力异常 密封圈") == []
    assert [hit.document.doc_id for hit in index.search("脉冲波形畸变")] == ["target"]
