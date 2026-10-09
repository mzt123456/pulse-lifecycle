"""向量检索、混合融合与降级路径的用例。

测试用确定性的假向量化器：不联网，但保留"语义相近则向量相近"的性质，
才能真正验证融合与过滤逻辑，而不是只验证代码能跑。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai import index_store
from app.ai.document import CaseDocument
from app.ai.embedding import EmbeddingError
from app.ai.retriever import BM25Index, SearchHit, fuse_hits
from app.ai.vector_index import VectorIndex
from app.api.v1.ai import get_embedder
from app.api.v1.ai import get_chat_client

DIAGNOSIS = "/api/v1/ai/diagnosis"

CONCEPTS = ("密封", "信号", "软件", "齿轮", "耗材")


class StubEmbedder:
    """按概念词是否出现构造向量——语义相近的文本向量就相近。"""

    name = "stub:concepts:v1"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return [[1.0 if concept in text else 0.0 for concept in CONCEPTS] for text in texts]


class CountingEmbedder(StubEmbedder):
    """记录被调用次数，用于验证索引缓存与失败冷却。"""


@pytest.fixture
def llm_override(api_client: TestClient):
    """这些用例只关心检索通道，模型统一置空（降级为只返回相似案例）。"""

    def install(client_impl: Any) -> Any:
        api_client.app.dependency_overrides[get_chat_client] = lambda: client_impl
        return client_impl

    install(None)
    yield install
    api_client.app.dependency_overrides.pop(get_chat_client, None)


def _doc(doc_id: str, text: str, **payload: object) -> CaseDocument:
    return CaseDocument(
        source="synthetic", doc_id=doc_id, title=doc_id, text=text, payload=dict(payload)
    )


def _hit(doc_id: str, score: float, terms: tuple[str, ...] = ()) -> SearchHit:
    return SearchHit(document=_doc(doc_id, doc_id), score=score, matched_terms=terms)


# ------------------------------------------------------------------ 向量索引


def test_vector_index_orders_by_cosine_similarity() -> None:
    documents = [
        _doc("seal", "密封面渗漏，压力保持不住"),
        _doc("signal", "地面解码误码率偏高"),
        _doc("software", "地面软件提示通讯超时"),
    ]
    index = VectorIndex(documents, StubEmbedder().embed([item.text for item in documents]))

    hits = index.search(StubEmbedder().embed(["密封圈老化导致渗漏"])[0], top_k=3)

    assert [hit.document.doc_id for hit in hits] == ["seal"]


def test_vector_index_respects_payload_filters() -> None:
    documents = [
        _doc("a", "密封面渗漏", fault_type="密封失效"),
        _doc("b", "密封面渗漏", fault_type="机械故障"),
    ]
    index = VectorIndex(documents, StubEmbedder().embed([item.text for item in documents]))
    vector = StubEmbedder().embed(["密封失效"])[0]

    hits = index.search(vector, top_k=5, filters={"fault_type": "机械故障"})

    assert [hit.document.doc_id for hit in hits] == ["b"]


def test_vector_index_returns_nothing_for_empty_query_vector() -> None:
    index = VectorIndex([_doc("a", "密封面渗漏")], [[0.0] * len(CONCEPTS)])
    assert index.search([0.0] * len(CONCEPTS)) == []
    assert index.search([0.0] * len(CONCEPTS), top_k=0) == []


# ------------------------------------------------------------------ 融合


def test_fusion_boosts_documents_found_by_both_channels() -> None:
    bm25 = [_hit("both", 8.0, ("密封",)), _hit("only_bm25", 4.0, ("压力",))]
    vector = [_hit("both", 0.9), _hit("only_vector", 0.8)]

    fused = fuse_hits(bm25, vector, top_k=3, vector_weight=0.5)

    assert [hit.document.doc_id for hit in fused] == ["both", "only_vector", "only_bm25"]
    # 两路都命中的文档分数应当高于只被一路命中的
    assert fused[0].score > fused[1].score


def test_fusion_keeps_bm25_explanation_terms() -> None:
    fused = fuse_hits([_hit("a", 5.0, ("密封", "老化"))], [_hit("a", 0.7)], top_k=1)
    assert fused[0].matched_terms == ("密封", "老化")


def test_fusion_with_pure_vector_weight_ignores_bm25_scores() -> None:
    bm25 = [_hit("bm25_top", 100.0)]
    vector = [_hit("vector_top", 0.95)]

    fused = fuse_hits(bm25, vector, top_k=2, vector_weight=1.0)

    assert fused[0].document.doc_id == "vector_top"


# ------------------------------------------------------------------ 缓存与降级


def test_index_store_reuses_cached_vectors(api_client: TestClient, session_factory) -> None:
    index_store.clear_corpus_cache()
    embedder = CountingEmbedder()
    with session_factory() as session:
        index_store.get_indexes(session, embedder=embedder)
        index_store.get_indexes(session, embedder=embedder)

    assert len(embedder.calls) == 1, "同一份语料不应重复向量化"


def test_index_store_notes_failure_and_cools_down(api_client: TestClient, session_factory) -> None:
    index_store.clear_corpus_cache()
    embedder = CountingEmbedder(error=EmbeddingError("HTTP 401"))
    with session_factory() as session:
        first = index_store.get_indexes(session, embedder=embedder)
        second = index_store.get_indexes(session, embedder=embedder)

    assert first.vector is None
    assert first.vector_note and "向量索引不可用" in first.vector_note
    assert second.vector is None
    # 冷却期内不重复尝试，避免每个请求都白等一次超时
    assert len(embedder.calls) == 1


def test_diagnosis_degrades_to_bm25_when_embedding_fails(
    api_client: TestClient,
    auth_headers: dict[str, str],
    llm_override,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_override(None)
    api_client.app.dependency_overrides[get_embedder] = lambda: StubEmbedder(
        error=EmbeddingError("HTTP 500")
    )
    index_store.clear_corpus_cache()
    try:
        response = api_client.post(
            DIAGNOSIS,
            headers=auth_headers,
            json={"description": "下井后压力保持不住"},
        )
    finally:
        api_client.app.dependency_overrides.pop(get_embedder, None)
        index_store.clear_corpus_cache()

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["retrieval"]["mode"] == "bm25"
    assert data["retrieval"]["note"] and "向量" in data["retrieval"]["note"]
    assert data["matches"], "向量不可用时关键词检索仍要给出结果"


def test_diagnosis_reports_hybrid_mode(
    api_client: TestClient, auth_headers: dict[str, str], llm_override
) -> None:
    llm_override(None)
    api_client.app.dependency_overrides[get_embedder] = lambda: StubEmbedder()
    index_store.clear_corpus_cache()
    try:
        data = api_client.post(
            DIAGNOSIS,
            headers=auth_headers,
            json={"description": "密封面渗漏，压力保持不住"},
        ).json()["data"]
    finally:
        api_client.app.dependency_overrides.pop(get_embedder, None)
        index_store.clear_corpus_cache()

    assert data["retrieval"]["mode"] == "hybrid"
    assert data["retrieval"]["vector_candidates"] > 0
    assert data["matches"], "混合检索应当能给出候选"
