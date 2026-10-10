"""向量化：把语料与查询变成向量（用框架的 OpenAIEmbeddings）。

只留一个协议与一个构造入口：

- 检索层只依赖 `Embedder` 协议（`embed(texts)` 与 `name`），换提供方只改 `build_embedder`；
- `name` 参与索引缓存键，所以换模型或换维度会自动重建索引，不会拿旧向量算相似度；
- 分批（`chunk_size`）、重试、请求构造交给框架；
  只有一处框架默认值必须改：`check_embedding_ctx_length=False`——那是给 OpenAI 用的
  tiktoken 预切分，第三方兼容端点（通义）不适用。

本地模型（语料不出内网）不预埋实现：需要时接 `langchain-huggingface` 的
`HuggingFaceEmbeddings`，同样实现 `Embedder` 协议即可，不装依赖就不放死代码。

失败一律抛 `EmbeddingError`：调用方据此退回纯 BM25，检索降级不能让诊断不可用。
"""

from __future__ import annotations

import logging
from typing import Protocol

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings

logger = logging.getLogger(__name__)

# 第三方兼容端点的单次请求条数限制（通义为 10 条/次）
DEFAULT_BATCH_SIZE = 10


class EmbeddingError(Exception):
    """向量化失败：网络、鉴权或返回体不合法。"""


class Embedder(Protocol):
    """向量化协议。"""

    # 用于索引缓存键：换模型或换维度必须重建索引
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class LangChainEmbedder:
    """OpenAI 兼容端点的向量化（框架负责分批、重试与请求构造）。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int | None = None,
        timeout: float = 30.0,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.model = model
        self.name = f"api:{base_url.rstrip('/')}:{model}:{dimensions or 'default'}"
        self._embedder = OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            dimensions=dimensions,
            check_embedding_ctx_length=False,
            chunk_size=max(1, batch_size),
            request_timeout=timeout,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = self._embedder.embed_documents(list(texts))
        except Exception as exc:  # 网络/鉴权/限流等统一转成 EmbeddingError，调用方据此降级
            logger.warning("向量化失败：%s", type(exc).__name__)
            raise EmbeddingError(f"向量化失败：{type(exc).__name__}") from exc
        return [[float(value) for value in vector] for vector in vectors]


def build_embedder(settings: Settings) -> Embedder | None:
    """按配置构造向量化器；未启用或缺少必要条件时返回 None（退回纯 BM25）。"""
    provider = (settings.embedding_provider or "none").strip().lower()
    if provider in {"", "none", "off"}:
        return None

    if provider == "api":
        if not settings.embedding_api_key:
            logger.warning("EMBEDDING_PROVIDER=api 但没有配置 EMBEDDING_API_KEY，退回纯 BM25")
            return None
        return LangChainEmbedder(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.embedding_timeout_seconds,
        )

    if provider == "local":
        logger.warning(
            "本次未内置本地向量模型实现：接入 langchain-huggingface 的 HuggingFaceEmbeddings 即可"
            "（语料不出内网），当前退回纯 BM25"
        )
        return None

    logger.warning("未知的 EMBEDDING_PROVIDER：%s，退回纯 BM25", provider)
    return None
