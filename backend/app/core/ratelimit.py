"""进程内滑动窗口限流，用于登录等敏感接口。

单实例部署够用（编写报告阶段 6 的部署是单台服务器）；生产环境还会在 Nginx
按 IP 限流作为第一道闸门，这里作为应用层兜底。
"""

from collections import defaultdict, deque
from time import monotonic

from fastapi import Request, status

from app.core.config import get_settings
from app.core.errors import BusinessError, ErrorCode


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int | None = None) -> bool:
        """在窗口内未达到上限则记一次并放行。"""
        effective = limit if limit is not None else self.limit
        now = monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= effective:
            return False
        hits.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


def client_ip(request: Request) -> str:
    """取来源 IP，优先使用反向代理透传的地址。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# 登录限流器：按来源 IP 计数，默认每分钟 10 次
login_limiter = SlidingWindowLimiter(limit=get_settings().login_rate_limit_per_minute)


def enforce_login_rate_limit(request: Request) -> None:
    """登录接口限流依赖：超限返回 42900。"""
    settings = get_settings()
    ip = client_ip(request)
    if not login_limiter.allow(ip, limit=settings.login_rate_limit_per_minute):
        raise BusinessError(
            ErrorCode.TOO_MANY_REQUESTS,
            "登录请求过于频繁，请稍后再试",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
