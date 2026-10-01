"""认证接口用例：登录、刷新、注销、当前用户与锁定策略。"""

from datetime import timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.timeutil import utc_now
from app.models.user import User

LOGIN = "/api/v1/auth/login"


def _login(client: TestClient, test_admin: dict[str, str]) -> dict:
    response = client.post(
        LOGIN, json={"username": test_admin["username"], "password": test_admin["password"]}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_login_returns_tokens_and_permissions(
    api_client: TestClient, test_admin: dict[str, str]
) -> None:
    data = _login(api_client, test_admin)

    assert data["token_type"] == "bearer"
    assert data["access_token"] and data["refresh_token"]
    assert data["expires_in"] == get_settings().access_token_expire_minutes * 60
    assert data["user"]["username"] == test_admin["username"]
    assert "系统管理员" in data["user"]["roles"]
    assert "equipment.view" in data["user"]["permissions"]
    assert "user.manage" in data["user"]["permissions"]


def test_login_with_wrong_password_is_rejected(
    api_client: TestClient, test_admin: dict[str, str]
) -> None:
    response = api_client.post(
        LOGIN, json={"username": test_admin["username"], "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_me_requires_token(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_me_returns_current_user(api_client: TestClient, test_admin: dict[str, str]) -> None:
    data = _login(api_client, test_admin)

    response = api_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["username"] == test_admin["username"]


def test_expired_access_token_reports_40101(api_client: TestClient) -> None:
    settings = get_settings()
    now = utc_now()
    expired = jwt.encode(
        {
            "sub": "1",
            "type": "access",
            "jti": "expired-in-api-test",
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert response.json()["code"] == 40101


def test_refresh_rotates_token_and_revokes_old_one(
    api_client: TestClient, test_admin: dict[str, str]
) -> None:
    data = _login(api_client, test_admin)

    refreshed = api_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text
    new_data = refreshed.json()["data"]
    assert new_data["refresh_token"] != data["refresh_token"]

    reused = api_client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert reused.status_code == 401
    assert reused.json()["code"] == 40100


def test_logout_revokes_refresh_token(
    api_client: TestClient, test_admin: dict[str, str]
) -> None:
    data = _login(api_client, test_admin)

    logout = api_client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert logout.status_code == 200

    again = api_client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert again.status_code == 401


def test_account_locks_after_max_attempts(
    api_client: TestClient, session_factory: sessionmaker[Session], locked_user: int
) -> None:
    settings = get_settings()

    for _ in range(settings.max_login_attempts):
        response = api_client.post(
            LOGIN, json={"username": "lock_test", "password": "wrong-password"}
        )
        assert response.status_code == 401

    blocked = api_client.post(
        LOGIN, json={"username": "lock_test", "password": "lock-test-password"}
    )
    assert blocked.status_code == 403
    assert "锁定" in blocked.json()["message"]

    with session_factory() as session:
        user = session.get(User, locked_user)
        assert user is not None and user.locked_until is not None
