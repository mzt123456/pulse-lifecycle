"""登录限流与跨域收紧的用例。"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode
from app.core.ratelimit import SlidingWindowLimiter, login_limiter
from app.main import create_app

LOGIN = "/api/v1/auth/login"


def test_sliding_window_blocks_after_limit() -> None:
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)

    assert [limiter.allow("1.2.3.4") for _ in range(3)] == [True, True, True]
    assert limiter.allow("1.2.3.4") is False
    # 不同来源互不影响
    assert limiter.allow("5.6.7.8") is True

    limiter.reset("1.2.3.4")
    assert limiter.allow("1.2.3.4") is True


def test_login_is_rate_limited_by_ip(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "login_rate_limit_per_minute", 2)
    login_limiter.reset()
    try:
        first = api_client.post(LOGIN, json={"username": "no_such_user", "password": "x"})
        second = api_client.post(LOGIN, json={"username": "no_such_user", "password": "x"})
        third = api_client.post(LOGIN, json={"username": "no_such_user", "password": "x"})
    finally:
        login_limiter.reset()

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert third.json()["code"] == ErrorCode.TOO_MANY_REQUESTS
    assert "过于频繁" in third.json()["message"]


def test_cors_wildcard_is_rejected_at_startup() -> None:
    with pytest.raises(ValueError) as exc:
        create_app(Settings(_env_file=None, cors_origins="*"))

    assert "通配符" in str(exc.value)


def test_cors_allowlist_is_applied() -> None:
    settings = Settings(_env_file=None, cors_origins="http://localhost:5173")
    app = create_app(settings)

    # 白名单里的来源会拿到跨域响应头，不在名单里的不会
    allowed = TestClient(app).get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    blocked = TestClient(app).get("/api/v1/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in blocked.headers
