"""向量化：把语料与查询变成向量，供向量检索使用。

两个实现，按配置切换：

- `OpenAICompatibleEmbedder`：走 OpenAI 兼容的 /embeddings 接口（通义 text-embedding-v4、
  智谱 embedding-3 都兼容），一个 key 就能用；
- `LocalBGEEmbedder`：本地 sentence-transformers 跑 BGE 中文模型，语料不出内网，
  代价是要装 torch 并下载模型权重。

为什么把提供方做成可插拔：这两种选择的取舍不是技术优劣，而是场景差异——
开发演示用 API 快、上生产要讲数据不出域就用本地模型。检索层只依赖 `Embedder` 协议。

失败一律抛 EmbeddingError：调用方据此退回纯 BM25，检索降级不能让诊断不可用。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

# 接口对单次请求的文本条数有限制，分批送
DEFAULT_BATCH_SIZE = 10


class EmbeddingError(Exception):
    """向量化失败：网络、鉴权、返回体不合法或本地模型不可用。"""


class Embedder(Protocol):
    """向量化协议。"""

    # 用于缓存键：换模型或换维度必须重建索引
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAICompatibleEmbedder:
    """OpenAI 兼容的向量接口客户端，带重试与分批。"""

    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        batch_size: int = DEFAULT_BATCH_SIZE,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.batch_size = max(1, batch_size)
        self._client = client
        self.name = f"api:{self.base_url}:{model}:{dimensions or 'default'}"

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(min(0.5 * 2 ** (attempt - 1), 4.0))
            try:
                if self._client is not None:
                    response = self._client.post(url, json=payload, headers=headers, timeout=self.timeout)
                else:
                    with httpx.Client(timeout=self.timeout) as client:
                        response = client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("向量化请求失败（第 %s 次）：%s", attempt + 1, exc)
                continue

            if response.status_code in self.RETRY_STATUS:
                last_error = EmbeddingError(f"向量服务返回 {response.status_code}")
                continue
            if response.status_code >= 400:
                # 不回显响应正文，避免把可能的敏感信息写进日志
                raise EmbeddingError(f"向量化失败：HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise EmbeddingError("向量服务返回的不是 JSON") from exc

        raise EmbeddingError(f"向量化失败：{last_error or '未知错误'}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            payload: dict[str, Any] = {"model": self.model, "input": batch}
            if self.dimensions:
                payload["dimensions"] = self.dimensions
            data = self._post(payload)

            items = data.get("data")
            if not isinstance(items, list) or len(items) != len(batch):
                raise EmbeddingError("向量服务返回条数与请求不一致")
            # 接口不保证顺序，按 index 归位
            ordered = sorted(items, key=lambda item: item.get("index", 0))
            for item in ordered:
                vector = item.get("embedding")
                if not isinstance(vector, list) or not vector:
                    raise EmbeddingError("向量服务返回了空的向量")
                vectors.append([float(value) for value in vector])
        return vectors


class LocalBGEEmbedder:
    """本地 BGE 模型：语料不出内网，代价是要装 torch 并下载模型权重。

    导入放在方法内：没装 sentence-transformers 的环境不应该因为 import 就起不来。
    """

    def __init__(self, model_name: str, *, device: str | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self.name = f"local:{model_name}"
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # 没装依赖时给出明确指引
                raise EmbeddingError(
                    "本地向量模型需要安装 sentence-transformers（含 torch）"
                ) from exc
            logger.info("加载本地向量模型：%s", self.model_name)
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            matrix = self._load().encode(texts, normalize_embeddings=True, show_progress_bar=False)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"本地向量模型调用失败：{exc}") from exc
        return [[float(value) for value in row] for row in matrix]


def build_embedder(settings: Settings) -> Embedder | None:
    """按配置构造向量化器；未启用或缺少必要条件时返回 None（退回纯 BM25）。"""
    provider = (settings.embedding_provider or "none").strip().lower()
    if provider in {"", "none", "off"}:
        return None

    if provider == "api":
        if not settings.embedding_api_key:
            logger.warning("EMBEDDING_PROVIDER=api 但没有配置 EMBEDDING_API_KEY，退回纯 BM25")
            return None
        return OpenAICompatibleEmbedder(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.embedding_timeout_seconds,
        )

    if provider == "local":
        return LocalBGEEmbedder(settings.embedding_model, device=settings.embedding_device or None)

    logger.warning("未知的 EMBEDDING_PROVIDER：%s，退回纯 BM25", provider)
    return None
