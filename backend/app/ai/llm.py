"""大模型接入层：OpenAI 兼容协议、超时重试与降级。

只用 httpx，不引入各家 SDK：DeepSeek、通义、智谱以及本地 Ollama 都提供
OpenAI 兼容的 `/chat/completions`，换模型只改 base_url 与模型名。

失败一律抛 LLMError，由业务层决定降级方式——检索链路本身不依赖模型，
模型不可用时接口仍能返回相似案例，这也是生产系统该有的行为。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """大模型调用失败：网络异常、超时、返回体不合法或不是 JSON。"""


class ChatClient(Protocol):
    """生成层依赖的最小接口，便于测试替换与后续接入本地模型。"""

    model: str

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """要求模型返回 JSON 对象；不满足约定时抛 LLMError。"""


@dataclass(frozen=True)
class ToolCall:
    """模型要求调用的一次工具。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatTurn:
    """一轮模型输出：要么是最终回答，要么是要调用的工具（可能多个）。"""

    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class TokenUsage:
    """一次调用的 token 用量：单次成本 = 输入 × 输入单价 + 输出 × 输出单价。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def merge(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    @classmethod
    def from_payload(cls, usage: Any) -> "TokenUsage":
        if not isinstance(usage, dict):
            return cls()
        return cls(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )


class ToolCallingClient(Protocol):
    """Agent 循环依赖的接口：走各家兼容的 function calling。"""

    model: str

    def complete_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatTurn:
        ...


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """function calling 的 arguments 是 JSON 字符串，解析失败时按空参数处理。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("工具参数不是合法 JSON，按空参数处理：%s", str(raw)[:120])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_turn(message: dict[str, Any]) -> ChatTurn:
    """把模型返回的 message 解析成一轮输出。"""
    calls: list[ToolCall] = []
    for index, item in enumerate(message.get("tool_calls") or []):
        function = item.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        calls.append(
            ToolCall(
                id=str(item.get("id") or f"call_{index}"),
                name=str(name),
                arguments=_parse_arguments(function.get("arguments")),
            )
        )
    content = message.get("content")
    return ChatTurn(content=content.strip() if isinstance(content, str) and content.strip() else None,
                    tool_calls=tuple(calls))


def extract_json(content: str) -> dict[str, Any]:
    """从模型输出里取出 JSON 对象。

    即使提示词要求「只输出 JSON」，模型仍可能套上 ```json 代码块或加一句
    说明文字，这里做一次容错解析，解析不了才判定失败。
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("模型返回的内容不是 JSON 对象") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"模型返回的 JSON 无法解析：{exc}") from exc

    if not isinstance(data, dict):
        raise LLMError("模型返回的 JSON 不是对象")
    return data


class OpenAICompatibleClient:
    """OpenAI 兼容的对话客户端。"""

    # 这类状态码属于暂时性故障，重试有意义；4xx 参数错误重试也没用。
    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._client = client
        # 最近一次调用的用量；评测脚本与成本观察直接读它
        self.last_usage = TokenUsage()

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            if attempt:
                # 退避 0.5s、1s……最多 4s；模型服务偶发抖动时不必立刻降级
                time.sleep(min(0.5 * 2 ** (attempt - 1), 4.0))
            try:
                if self._client is not None:
                    response = self._client.post(url, json=payload, headers=headers, timeout=self.timeout)
                else:
                    with httpx.Client(timeout=self.timeout) as client:
                        response = client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("大模型请求失败（第 %s 次）：%s", attempt + 1, exc)
                continue

            if response.status_code in self.RETRY_STATUS:
                last_error = LLMError(f"大模型服务返回 {response.status_code}")
                logger.warning("大模型返回 %s，准备重试", response.status_code)
                continue
            if response.status_code >= 400:
                # 不回显响应正文，避免把可能的敏感信息写进日志
                raise LLMError(f"大模型调用失败：HTTP {response.status_code}")

            try:
                body = response.json()
            except ValueError as exc:
                raise LLMError("大模型返回的不是 JSON") from exc
            self.last_usage = TokenUsage.from_payload(body.get("usage"))
            return body

        raise LLMError(f"大模型调用失败：{last_error or '未知错误'}")

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        data = self._post(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
        )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("大模型返回结构不符合预期") from exc
        return extract_json(content)

    def complete_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> ChatTurn:
        """带工具的一轮对话：模型自己决定是继续调工具还是给出结论。"""
        data = self._post(
            {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": tools,
                "tool_choice": "auto",
            }
        )
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("大模型返回结构不符合预期") from exc
        return parse_turn(message)


def build_chat_client(settings: Settings) -> OpenAICompatibleClient | None:
    """按配置构造客户端；没有 API Key 时返回 None，由调用方降级。"""
    if not settings.llm_api_key:
        return None
    return OpenAICompatibleClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
