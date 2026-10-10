"""语料索引缓存：避免每次诊断请求都重新分词、重建索引、重复向量化。

缓存键取故障记录表的「条数 + 最大 ID + 最大更新时间」——这三个值在一起，
新增、修改、删除都会让缓存自动失效，不必手工清缓存。开启向量检索时，
缓存键再加上向量模型名——换模型必须重建索引，否则维度或语义空间对不上。

索引在单进程内共享，多进程部署时每个 worker 各持一份，属于可接受的重复。
向量化失败会记下时间，短时间内不重复尝试：否则每个请求都要白等一次超时。
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.corpus import build_corpus
from app.ai.embedding import Embedder, EmbeddingError
from app.ai.retriever import BM25Index
from app.ai.vector_index import VectorIndex
from app.models.fault import FaultRecord
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger(__name__)

# 向量化失败后的冷却时间：避免每个请求都去等一次超时
EMBEDDING_RETRY_SECONDS = 60


@dataclass(frozen=True)
class IndexBundle:
    """一次检索要用的索引：BM25 一定有，向量索引可用时才有。"""

    bm25: BM25Index
    vector: VectorIndex | None = None
    vector_note: str | None = None
    embedder_name: str | None = None


_CACHE: dict[tuple[Any, ...], IndexBundle] = {}
_EMBEDDING_FAILED_AT: dict[tuple[Any, ...], float] = {}
# 增量向量化缓存：向量模型名 → {doc_id: 正文指纹}
_TEXT_HASHES: dict[str, dict[str, str]] = {}
# 向量模型名 → {doc_id: 向量}，只对正文未变的文档复用
_VECTOR_CACHE: dict[str, dict[str, list[float]]] = {}
_LOCK = threading.Lock()


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def corpus_fingerprint(db: Session) -> tuple[Any, ...]:
    """故障记录 + 知识库的轻量指纹，用于判断语料是否需要重建。"""
    count, max_id, max_updated = db.execute(
        select(
            func.count(FaultRecord.id),
            func.max(FaultRecord.id),
            func.max(FaultRecord.updated_at),
        )
    ).one()
    knowledge_count, knowledge_max_updated, chunk_count, chunk_max_id = db.execute(
        select(
            func.count(KnowledgeDocument.id),
            func.max(KnowledgeDocument.updated_at),
            func.count(KnowledgeChunk.id),
            func.max(KnowledgeChunk.id),
        )
        .select_from(KnowledgeDocument)
        .outerjoin(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
    ).one()
    return (
        count or 0,
        max_id or 0,
        max_updated or "",
        knowledge_count or 0,
        knowledge_max_updated or "",
        chunk_count or 0,
        chunk_max_id or 0,
    )


def get_indexes(
    db: Session,
    *,
    include_synthetic: bool = True,
    embedder: Embedder | None = None,
) -> IndexBundle:
    """取语料索引；优先命中缓存，指纹或向量模型变化时重建。"""
    fingerprint = corpus_fingerprint(db)
    key = (fingerprint, include_synthetic, embedder.name if embedder else None)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    documents = build_corpus(db, include_synthetic=include_synthetic)
    bm25 = BM25Index(documents)
    bundle = IndexBundle(bm25=bm25, embedder_name=embedder.name if embedder else None)

    if embedder is not None:
        failure_key = (fingerprint, include_synthetic, embedder.name)
        failed_at = _EMBEDDING_FAILED_AT.get(failure_key)
        if failed_at is not None and time.time() - failed_at < EMBEDDING_RETRY_SECONDS:
            bundle = IndexBundle(
                bm25=bm25,
                vector_note="向量索引暂不可用（上次向量化失败，稍后自动重试）",
                embedder_name=embedder.name,
            )
        else:
            try:
                hashes = {document.doc_id: _text_hash(document.text) for document in documents}
                cached_hashes = _TEXT_HASHES.get(embedder.name, {})
                cached_vectors = _VECTOR_CACHE.get(embedder.name, {})

                # 增量：正文没变的文档直接复用上次的向量，只对新文档/改过的文档调接口
                pending = [
                    document
                    for document in documents
                    if cached_hashes.get(document.doc_id) != hashes[document.doc_id]
                    or document.doc_id not in cached_vectors
                ]
                vector_by_id = {
                    document.doc_id: cached_vectors[document.doc_id]
                    for document in documents
                    if document.doc_id in cached_vectors
                    and cached_hashes.get(document.doc_id) == hashes[document.doc_id]
                }
                if pending:
                    fresh = embedder.embed([document.text for document in pending])
                    for document, vector in zip(pending, fresh, strict=True):
                        vector_by_id[document.doc_id] = vector

                vectors = [vector_by_id[document.doc_id] for document in documents]
                bundle = IndexBundle(
                    bm25=bm25, vector=VectorIndex(documents, vectors), embedder_name=embedder.name
                )
                _TEXT_HASHES[embedder.name] = hashes
                _VECTOR_CACHE[embedder.name] = vector_by_id
                _EMBEDDING_FAILED_AT.pop(failure_key, None)
                logger.info(
                    "语料索引重建：共 %s 条，其中新向量化 %s 条（复用 %s 条）",
                    len(documents),
                    len(pending),
                    len(documents) - len(pending),
                )
            except EmbeddingError as exc:
                # 向量化失败不影响可用性：退回纯 BM25，并把原因带出去
                _EMBEDDING_FAILED_AT[failure_key] = time.time()
                bundle = IndexBundle(
                    bm25=bm25, vector_note=f"向量索引不可用：{exc}", embedder_name=embedder.name
                )

    with _LOCK:
        # 只保留最新一份，避免指纹持续变化时缓存无限增长
        _CACHE.clear()
        _CACHE[key] = bundle
    return bundle


def get_corpus_index(db: Session, *, include_synthetic: bool = True) -> BM25Index:
    """只要 BM25 的快捷入口（诊断与 MCP 之外的调用方仍在用）。"""
    return get_indexes(db, include_synthetic=include_synthetic).bm25


def clear_corpus_cache() -> None:
    """测试与配置变更时手工清缓存。"""
    with _LOCK:
        _CACHE.clear()
        _EMBEDDING_FAILED_AT.clear()
        _TEXT_HASHES.clear()
        _VECTOR_CACHE.clear()
