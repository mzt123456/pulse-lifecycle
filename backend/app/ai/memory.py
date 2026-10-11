"""短期会话记忆的**会话目录**：会话内容存在 LangGraph 的检查点里，这里只管生命周期。

分工是刻意的：

- **内容**归 checkpointer（`graph_agent.get_checkpointer()`，`InMemorySaver`）：
  按 `thread_id`（就是会话 ID）保存每轮图状态，消息、工具调用与工具返回都在里面，
  恢复与裁剪由 `graph_agent._prepare` 负责；
- **目录**归这里：会话 ID 的发放与归属、最后活跃时间、TTL 与容量上限。
  检查点存储本身没有过期与容量概念，不清理就会一直涨，
  所以过期、淘汰、主动忘记这三条路径都要顺手删掉对应的线程。

边界写在实现里：

- **会话 ID 由服务端发放**（uuid4），客户端只负责回传：不认识或不属于调用者的 ID 一律当新会话；
- **进程内存储**：单进程部署有效。多 worker 或多实例时，检查点换 `langgraph-checkpoint-redis`、
  目录换 Redis（对外接口不变）；
- **绑定用户**：拿别人的会话 ID 读不到内容，也改不动别人的会话。
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


def _drop_checkpoint(conversation_id: str) -> None:
    """删掉会话在检查点里的线程。

    放在函数里延迟导入：会话目录不该在模块加载期就把编排层拖进来。
    """
    from app.ai import graph_agent

    try:
        graph_agent.get_checkpointer().delete_thread(conversation_id)
    except Exception:  # pragma: no cover - 清理失败不该影响业务
        logger.warning("删除会话检查点失败：%s", conversation_id, exc_info=True)


@dataclass
class Conversation:
    """一条会话目录：谁在用、最后一次活跃是什么时候。"""

    conversation_id: str
    user_id: int
    updated_at: float = field(default_factory=time.monotonic)


class ConversationMemory:
    """带 TTL 与容量上限的会话目录。线程安全，单进程内共享。"""

    def __init__(self, *, ttl_seconds: float, max_conversations: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_conversations = max(1, max_conversations)
        self._items: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- 读

    def owns(self, conversation_id: str | None, user_id: int) -> bool:
        """这个会话是否已登记、且属于该用户。"""
        key = (conversation_id or "").strip()
        if not key:
            return False
        with self._lock:
            self._purge_expired()
            item = self._items.get(key)
            if item is None:
                return False
            if item.user_id != user_id:
                # 不区分"不存在"与"不是你的"，避免会话 ID 被当成探测手段
                logger.warning("会话 %s 不属于当前用户，按新会话处理", key)
                return False
            return True

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._purge_expired()
            return {
                "conversations": len(self._items),
                "max_conversations": self.max_conversations,
                "ttl_seconds": int(self.ttl_seconds),
            }

    # ------------------------------------------------------------- 写

    def register(self, conversation_id: str | None, user_id: int) -> str:
        """登记一次使用，返回本次实际使用的会话 ID（不认识旧 ID 时发一个新的）。"""
        key = (conversation_id or "").strip()
        with self._lock:
            self._purge_expired()
            item = self._items.get(key) if key else None
            if item is not None and item.user_id != user_id:
                # 别人的会话 ID：另开一个新会话，不覆盖也不写入对方的记录
                logger.warning("会话 %s 不属于当前用户，改为新建会话", key)
                item = None
            if item is None:
                key = uuid.uuid4().hex
                item = Conversation(conversation_id=key, user_id=user_id)
                self._items[key] = item
            item.updated_at = time.monotonic()
            self._items.move_to_end(key)
            self._evict_overflow()
            return key

    def clear(self, conversation_id: str, user_id: int) -> bool:
        """忘掉一个会话（目录 + 检查点）；不存在或不属于该用户时返回 False（幂等）。"""
        key = (conversation_id or "").strip()
        with self._lock:
            item = self._items.get(key)
            if item is None or item.user_id != user_id:
                return False
            del self._items[key]
        _drop_checkpoint(key)
        return True

    def reset(self) -> None:
        """清空全部会话：测试用，也可在服务优雅退出时调用。"""
        from app.ai import graph_agent

        with self._lock:
            self._items.clear()
        graph_agent.reset_checkpointer()

    # ------------------------------------------------------------- 内部

    def _purge_expired(self) -> None:
        if self.ttl_seconds <= 0:
            dropped = list(self._items)
            self._items.clear()
        else:
            deadline = time.monotonic() - self.ttl_seconds
            dropped = [key for key, item in self._items.items() if item.updated_at < deadline]
            for key in dropped:
                self._items.pop(key, None)
        for key in dropped:
            _drop_checkpoint(key)

    def _evict_overflow(self) -> None:
        while len(self._items) > self.max_conversations:
            evicted, _ = self._items.popitem(last=False)  # 最久未活跃的先走
            logger.info("会话数超过上限，淘汰最久未活跃的会话 %s", evicted)
            _drop_checkpoint(evicted)


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
