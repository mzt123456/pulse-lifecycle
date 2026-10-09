"""语料索引缓存：避免每次诊断请求都重新分词、重建索引、重复向量化。

缓存键取故障记录表的「条数 + 最大 ID + 最大更新时间」——这三个值在一起，
新增、修改、删除都会让缓存自动失效，不必手工清缓存。开启向量检索时，
缓存键再加上向量模型名——换模型必须重建索引，否则维度或语义空间对不上。

索引在单进程内共享，多进程部署时每个 worker 各持一份，属于可接受的重复。
向量化失败会记下时间，短时间内不重复尝试：否则每个请求都要白等一次超时。
"""

from __future__ import annotations

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
_LOCK = threading.Lock()


def corpus_fingerprint(db: Session) -> tuple[Any, ...]:
    """故障记录表的轻量指纹，用于判断语料是否需要重建。"""
    count, max_id, max_updated = db.execute(
        select(
            func.count(FaultRecord.id),
            func.max(FaultRecord.id),
            func.max(FaultRecord.updated_at),
        )
    ).one()
    return (count or 0, max_id or 0, max_updated or "")


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
                vectors = embedder.embed([document.text for document in documents])
                bundle = IndexBundle(
                    bm25=bm25, vector=VectorIndex(documents, vectors), embedder_name=embedder.name
                )
                _EMBEDDING_FAILED_AT.pop(failure_key, None)
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
