"""向量索引：内存矩阵 + 余弦相似度，接口与 BM25 对齐以便融合。

为什么不用向量库：语料目前几十条、真实数据到位后也就几千条，一个 numpy 矩阵的
暴力检索是毫秒级；为这个量级部署 Qdrant 属于过度设计，还多一套运维。
`VectorIndex` 的 `search` 与 `BM25Index.search` 返回同一套 `SearchHit`，
所以检索层往下（诊断、重排、工具）完全不用改。

向量在入库时归一化，检索时点积即余弦相似度，省一次除法。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

import numpy as np

from app.ai.document import CaseDocument
from app.ai.retriever import SearchHit

logger = logging.getLogger(__name__)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class VectorIndex:
    """把语料向量装进内存矩阵，按余弦相似度检索。"""

    def __init__(self, documents: Sequence[CaseDocument], vectors: Sequence[Sequence[float]]) -> None:
        if len(documents) != len(vectors):
            raise ValueError("文档数与向量数不一致")
        self._documents = list(documents)
        self._matrix = (
            _normalize(np.asarray(vectors, dtype=np.float32))
            if vectors
            else np.zeros((0, 0), dtype=np.float32)
        )
        logger.info("向量索引就绪：%s 条，维度 %s", len(self._documents), self.dimensions)

    def __len__(self) -> int:
        return len(self._documents)

    @property
    def dimensions(self) -> int:
        return int(self._matrix.shape[1]) if self._matrix.size else 0

    @property
    def documents(self) -> tuple[CaseDocument, ...]:
        return tuple(self._documents)

    def search(
        self,
        vector: Sequence[float],
        *,
        top_k: int = 5,
        filters: Mapping[str, object] | None = None,
        min_similarity: float = 0.0,
    ) -> list[SearchHit]:
        """按余弦相似度取前 K 条；相似度为负的一律丢掉（方向相反即不相关）。"""
        if top_k <= 0 or not self._documents:
            return []

        query = np.asarray([vector], dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm == 0:
            return []
        similarities = (self._matrix @ (query / norm).T).ravel()

        index_candidates = range(len(self._documents))
        if filters:
            index_candidates = [
                index
                for index in index_candidates
                if all(self._documents[index].payload.get(key) == value for key, value in filters.items())
            ]

        hits: list[SearchHit] = []
        for index in index_candidates:
            similarity = float(similarities[index])
            if similarity <= max(min_similarity, 0.0):
                continue
            hits.append(
                SearchHit(
                    document=self._documents[index],
                    score=round(similarity, 4),
                    matched_terms=(),  # 向量检索没有命中词，解释由重排的理由承担
                )
            )

        hits.sort(key=lambda hit: (-hit.score, hit.document.doc_id))
        return hits[:top_k]
