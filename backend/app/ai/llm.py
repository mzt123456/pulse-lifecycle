"""大模型接入：用 langchain-openai 的 ChatOpenAI 做调用，外面套一层薄适配。

**框架负责协议与健壮性**：HTTP 细节、重试（ChatOpenAI 自带 max_retries）、超时、
工具绑定（bind_tools）、消息对象与 API 负载的互转、把响应解析成 AIMessage（含 tool_calls）。

**这一层保留什么**：调用方只依赖两个方法（`complete_json` / `complete_with_tools`）与
`last_usage`，所以换模型、换厂商、乃至换回裸 HTTP 都只改这一个文件；
降级语义（一切失败都抛 LLMError，由业务层决定退化成"只返回相似案例"）与用量口径
（token 直接进返回体）也留在这里。

换模型只改 base_url 与模型名：DeepSeek 生成 + 通义向量现在就是这样并存。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """大模型调用失败：网络异常、超时、鉴权失败或返回体不合法。"""


@dataclass(frozen=True)
class TokenUsage:
    """一次调用的 token 用量：单次成本 = 输入 × 输入单价 + 输出 × 输出单价。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> "TokenUsage":
        """从 LangChain 的 usage_metadata 取值。"""
        if not metadata:
            return cls()
        return cls(
            prompt_tokens=int(metadata.get("input_tokens") or 0),
            completion_tokens=int(metadata.get("output_tokens") or 0),
            total_tokens=int(metadata.get("total_tokens") or 0),
        )


@dataclass(frozen=True)
class ToolCall:
    """模型要求调用的一次工具（参数已由框架解析成字典）。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatTurn:
    """一轮模型输出：要么是最终回答，要么是要调用的工具（可能多个）。"""

    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()


class ChatClient(Protocol):
    """生成层依赖的最小接口，便于测试替换与后续接入本地模型。"""

    model: str
    last_usage: TokenUsage

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """要求模型返回 JSON 对象；不满足约定时抛 LLMError。"""


class ToolCallingClient(Protocol):
    """Agent 循环依赖的接口：走各家的 function calling。"""

    model: str

    def complete_with_tools(
        self,
        *,
        messages: list[Any],
        tools: list[BaseTool],
    ) -> ChatTurn:
        ...


_JSON_PARSER = JsonOutputParser()


def parse_json(content: str) -> dict[str, Any]:
    """把模型返回的文本解析成 JSON 对象（用框架的 JsonOutputParser）。

    解析走 JSON 模式（`response_format=json_object`）时模型只返回 JSON，所以不需要
    "从散文里抠 JSON"那层容错；解析失败说明返回体不合约定，直接抛 LLMError 由业务层降级。
    """
    try:
        data = _JSON_PARSER.parse(content or "")
    except Exception as exc:  # 框架的解析异常类型较杂，统一收敛成 LLMError
        raise LLMError("模型返回的内容不是 JSON 对象") from exc
    if not isinstance(data, dict):
        raise LLMError("模型返回的 JSON 不是对象")
    return data


class LangChainChatClient:
    """基于 ChatOpenAI 的客户端，对外接口与之前保持一致。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        max_retries: int = 2,
        temperature: float = 0.2,
    ) -> None:
        self.model = model
        self.last_usage = TokenUsage()
        # 重试与超时交给框架；换模型只改 model 与 base_url
        self._model = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            temperature=temperature,
        )

    # ------------------------------------------------------------ 内部

    def _record(self, message: AIMessage) -> None:
        self.last_usage = TokenUsage.from_metadata(getattr(message, "usage_metadata", None))

    @staticmethod
    def _fail(action: str, exc: Exception) -> LLMError:
        # 不拼接异常正文与密钥，避免把敏感信息带进日志
        logger.warning("%s失败：%s", action, type(exc).__name__)
        return LLMError(f"{action}失败：{type(exc).__name__}")

    # ------------------------------------------------------------ 对外

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """要求模型返回 JSON 对象（走 response_format=json_object）。"""
        messages = [SystemMessage(system), HumanMessage(user)]
        try:
            response = self._model.bind(response_format={"type": "json_object"}).invoke(messages)
        except Exception as exc:  # 网络/鉴权/限流等统一转成 LLMError，由业务层决定降级
            raise self._fail("大模型调用", exc) from exc

        if not isinstance(response, AIMessage):
            raise LLMError("大模型返回结构不符合预期")
        self._record(response)
        content = response.content if isinstance(response.content, str) else str(response.content)
        return parse_json(content)

    def complete_with_tools(
        self,
        *,
        messages: list[Any],
        tools: list[BaseTool],
    ) -> ChatTurn:
        """带工具的一轮对话：模型自己决定是继续调工具还是给出结论。"""
        try:
            response = self._model.bind_tools(tools).invoke(messages)
        except Exception as exc:
            raise self._fail("大模型调用", exc) from exc

        if not isinstance(response, AIMessage):
            raise LLMError("大模型返回结构不符合预期")
        self._record(response)

        # 框架已经把 tool_calls 解析好（arguments 是字典），不用再自己解 JSON 字符串
        calls = tuple(
            ToolCall(
                id=str(item.get("id") or f"call_{index}"),
                name=str(item.get("name") or ""),
                arguments=item.get("args") if isinstance(item.get("args"), dict) else {},
            )
            for index, item in enumerate(response.tool_calls or [])
            if item.get("name")
        )
        content = response.content
        text = content.strip() if isinstance(content, str) and content.strip() else None
        return ChatTurn(content=text, tool_calls=calls)

    def stream_text(self, *, system: str, user: str) -> Iterator[str]:
        """流式输出（给前端逐字显示留的接口；SSE 与前端渲染还没接）。"""
        for chunk in self._model.stream([SystemMessage(system), HumanMessage(user)]):
            piece = getattr(chunk, "content", "")
            if isinstance(piece, str) and piece:
                yield piece


def build_chat_client(settings: Settings) -> LangChainChatClient | None:
    """按配置构造客户端；没有 API Key 时返回 None，由调用方降级。"""
    if not settings.llm_api_key:
        return None
    return LangChainChatClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
