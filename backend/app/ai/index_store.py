"""语料索引缓存：避免每次诊断请求都重新分词、重建 BM25 索引。

缓存键取故障记录表的「条数 + 最大 ID + 最大更新时间」——这三个值在一起，
新增、修改、删除都会让缓存自动失效，不必手工清缓存。索引在单进程内共享，
多进程部署时每个 worker 各持一份，属于可接受的重复。
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.corpus import build_corpus
from app.ai.retriever import BM25Index
from app.models.fault import FaultRecord

_CACHE: dict[tuple[Any, ...], BM25Index] = {}
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


def get_corpus_index(db: Session, *, include_synthetic: bool = True) -> BM25Index:
    """取语料索引；优先命中缓存，指纹变化时重建。"""
    key = (corpus_fingerprint(db), include_synthetic)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    index = BM25Index(build_corpus(db, include_synthetic=include_synthetic))
    with _LOCK:
        # 只保留最新一份，避免指纹持续变化时缓存无限增长
        _CACHE.clear()
        _CACHE[key] = index
    return index


def clear_corpus_cache() -> None:
    """测试与配置变更时手工清缓存。"""
    with _LOCK:
        _CACHE.clear()
