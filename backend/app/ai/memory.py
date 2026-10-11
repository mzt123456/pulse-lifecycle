"""短期会话记忆：把最近几轮问答留在服务端进程内，按会话 ID 续接。

为什么是这个形态，而不是 LangGraph 的 checkpointer 或一张会话表：

- 图的状态里带工具调用与工具返回（可能含已过期的数据），而这里刻意**只存问答正文**，
  两者口径不同，硬塞进图状态反而要额外过滤；
- 短期记忆按定义就是易失的：刷新页面、换个客户端可以接着聊，服务重启即失效。
  为它引入一张表，就要顺带回答"存多久、谁能看、删了算不算删"，当前阶段不值当。

边界写在实现里：

- **会话 ID 由服务端发放**（uuid4），客户端只负责回传：不认识或不属于调用者的 ID 一律当新会话；
- **进程内存储**：单进程部署有效。多 worker 或多实例时换成 Redis（接口不变，只换实现）；
- **绑定用户**：会话带 user_id，拿着别人的 ID 也读不到内容，也改不动别人的会话；
- **有上限**：超过 TTL 自动过期，最多保留 max_conversations 个，超了淘汰最久未活跃的；
- **有长度上限**：只保留最近 max_turns 轮，单条问题与回答各截断到 max_chars 字。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 与 agent.MAX_HISTORY_TURNS / MAX_HISTORY_CHARS 保持一致：记忆里存的就是喂给模型的那几轮
MAX_TURNS = 6
MAX_CHARS = 1500

@dataclass
class Conversation:
    """一个会话：归属用户 + 最近几轮问答。"""

    conversation_id: str
    user_id: int
    turns: list[tuple[str, str | None]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ConversationMemory:
    """带 TTL 与容量上限的会话存储。线程安全，单进程内共享。"""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_conversations: int,
        max_turns: int = MAX_TURNS,
        max_chars: int = MAX_CHARS,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_conversations = max(1, max_conversations)
        self.max_turns = max(1, max_turns)
        self.max_chars = max(1, max_chars)
        self._items: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- 读

    def resolve(self, conversation_id: str | None, user_id: int) -> list[tuple[str, str | None]]:
        """取该会话的历史轮次；不存在、已过期或不属于该用户时返回空列表。"""
        key = (conversation_id or "").strip()
        if not key:
            return []
        with self._lock:
            self._purge_expired()
            item = self._items.get(key)
            if item is None:
                return []
            if item.user_id != user_id:
                # 不区分"不存在"与"不是你的"，避免会话 ID 被当成探测手段
                logger.warning("会话 %s 不属于当前用户，按新会话处理", key)
                return []
            item.updated_at = time.monotonic()
            self._items.move_to_end(key)
            return list(item.turns)

    # ------------------------------------------------------------- 写

    def append(
        self,
        conversation_id: str | None,
        user_id: int,
        question: str,
        answer: str | None,
    ) -> str:
        """把本轮问答追加进会话，返回本次实际使用的会话 ID（不认识旧 ID 时发一个新的）。"""
        key = (conversation_id or "").strip()
        with self._lock:
            self._purge_expired()
            item = self._items.get(key) if key else None
            if item is not None and item.user_id != user_id:
                # 别人的会话 ID：另开一个新会话，不覆盖也不写入对方记录
                logger.warning("会话 %s 不属于当前用户，改为新建会话", key)
                item = None
            if item is None:
                key = uuid.uuid4().hex
                item = Conversation(conversation_id=key, user_id=user_id)
                self._items[key] = item

            with item.lock:
                text = str(question or "").strip()[: self.max_chars]
                if text:
                    reply = str(answer).strip()[: self.max_chars] if answer else None
                    item.turns.append((text, reply))
                    del item.turns[: -self.max_turns]
                item.updated_at = time.monotonic()

            self._items.move_to_end(key)
            self._evict_overflow()
            return key

    def clear(self, conversation_id: str, user_id: int) -> bool:
        """忘掉一个会话；不存在或不属于该用户时返回 False（不报错，天然幂等）。"""
        with self._lock:
            item = self._items.get(conversation_id)
            if item is None or item.user_id != user_id:
                return False
            del self._items[conversation_id]
            return True

    def reset(self) -> None:
        """清空全部会话：测试用，也可在服务优雅退出时调用。"""
        with self._lock:
            self._items.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._purge_expired()
            return {
                "conversations": len(self._items),
                "turns": sum(len(item.turns) for item in self._items.values()),
                "max_conversations": self.max_conversations,
                "ttl_seconds": int(self.ttl_seconds),
            }

    # ------------------------------------------------------------- 内部

    def _purge_expired(self) -> None:
        if self.ttl_seconds <= 0:
            self._items.clear()
            return
        deadline = time.monotonic() - self.ttl_seconds
        expired = [key for key, item in self._items.items() if item.updated_at < deadline]
        for key in expired:
            self._items.pop(key, None)

    def _evict_overflow(self) -> None:
        while len(self._items) > self.max_conversations:
            evicted, _ = self._items.popitem(last=False)  # 最久未活跃的先走
            logger.info("会话数超过上限，淘汰最久未活跃的会话 %s", evicted)


_MEMORY: ConversationMemory | None = None
_MEMORY_LOCK = threading.Lock()


def get_memory() -> ConversationMemory:
    """进程内单例；TTL 与容量取配置，测试可以直接换实例。"""
    global _MEMORY
    if _MEMORY is None:
        with _MEMORY_LOCK:
            if _MEMORY is None:
                settings = get_settings()
                _MEMORY = ConversationMemory(
                    ttl_seconds=settings.ai_memory_ttl_minutes * 60,
                    max_conversations=settings.ai_memory_max_conversations,
                )
    return _MEMORY
