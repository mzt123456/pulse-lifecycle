"""用户、角色与权限点管理用例：账号生命周期、角色分配、权限边界与保护规则。"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import Role

BASE = "/api/v1/system"


def _role_id(session_factory: sessionmaker[Session], name: str) -> int:
    with session_factory() as session:
        return session.execute(select(Role.id).where(Role.name == name)).scalar_one()


def _create(
    api_client: TestClient,
    headers: dict[str, str],
    *,
    username: str,
    password: str = "Init-passw0rd-1234",
    role_ids: list[int],
    real_name: str = "测试账号",
):
    return api_client.post(
        f"{BASE}/users",
        headers=headers,
        json={
            "username": username,
            "password": password,
            "real_name": real_name,
            "department": "测试岗",
            "role_ids": role_ids,
        },
    )


def _login(api_client: TestClient, username: str, password: str):
    return api_client.post("/api/v1/auth/login", json={"username": username, "password": password})


# ------------------------------------------------------------------ 权限边界


def test_user_management_requires_permission(
    api_client: TestClient, readonly_headers: dict[str, str]
) -> None:
    assert api_client.get(f"{BASE}/users", headers=readonly_headers).status_code == 403
    assert api_client.get(f"{BASE}/roles", headers=readonly_headers).status_code == 403
    assert api_client.get(f"{BASE}/permissions", headers=readonly_headers).status_code == 403
    assert api_client.post(f"{BASE}/users", headers=readonly_headers, json={}).status_code == 403


def test_list_users_returns_roles(
    api_client: TestClient, auth_headers: dict[str, str], test_admin: dict[str, str]
) -> None:
    response = api_client.get(f"{BASE}/users", headers=auth_headers, params={"page_size": 50})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    admin = next(item for item in data["items"] if item["username"] == test_admin["username"])
    assert admin["roles"] == ["系统管理员"]
    assert admin["is_active"] is True
    assert admin["last_login_at"]
    assert data["total"] >= 1


def test_permissions_and_roles_are_listed(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    permissions = api_client.get(f"{BASE}/permissions", headers=auth_headers).json()["data"]
    codes = {item["code"] for item in permissions["items"]}

    assert {"user.manage", "equipment.view", "knowledge.upload"} <= codes

    roles = api_client.get(f"{BASE}/roles", headers=auth_headers).json()["data"]["items"]
    admin_role = next(item for item in roles if item["name"] == "系统管理员")
    assert admin_role["is_builtin"] is True
    assert len(admin_role["permission_ids"]) == len(codes)  # 系统管理员拥有全部权限点


# ------------------------------------------------------------------ 账号生命周期


def test_create_user_can_login_with_assigned_permissions(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    created = _create(
        api_client,
        auth_headers,
        username="t_field",
        role_ids=[_role_id(session_factory, "现场技术员")],
        real_name="现场小王",
    )

    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["roles"] == ["现场技术员"]
    assert data["is_active"] is True

    login = _login(api_client, "t_field", "Init-passw0rd-1234")
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    # 现场技术员有 equipment.view，没有 equipment.create
    assert api_client.get("/api/v1/equipment", headers=headers).status_code == 200
    denied = api_client.post(
        "/api/v1/equipment", headers=headers, json={"equipment_no": "T-USER-1", "status": "待命"}
    )
    assert denied.status_code == 403


def test_create_user_rejects_duplicate_username(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    role = _role_id(session_factory, "只读用户")
    assert _create(api_client, auth_headers, username="t_dup", role_ids=[role]).status_code == 200

    again = _create(api_client, auth_headers, username="t_dup", role_ids=[role])

    assert again.status_code == 409
    assert again.json()["code"] == 40900


def test_create_user_validates_input(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    role = _role_id(session_factory, "只读用户")

    assert _create(api_client, auth_headers, username="ab", role_ids=[role]).status_code == 400
    assert _create(api_client, auth_headers, username="t_bad", password="short", role_ids=[role]).status_code == 400
    assert _create(api_client, auth_headers, username="t_norole", role_ids=[]).status_code == 400
    assert _create(api_client, auth_headers, username="t_norole2", role_ids=[999999]).status_code == 422


def test_update_user_roles_take_effect(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    _create(
        api_client,
        auth_headers,
        username="t_role_change",
        role_ids=[_role_id(session_factory, "现场技术员")],
    )
    login = _login(api_client, "t_role_change", "Init-passw0rd-1234")
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    user_id = login.json()["data"]["user"]["id"]

    updated = api_client.put(
        f"{BASE}/users/{user_id}",
        headers=auth_headers,
        json={"role_ids": [_role_id(session_factory, "只读用户")]},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["roles"] == ["只读用户"]
    # 权限按请求实时加载：同一个令牌，下一次请求的权限就已经变了
    me = api_client.get("/api/v1/auth/me", headers=headers).json()["data"]
    assert "equipment.view" in me["permissions"]
    assert "fault.create" not in me["permissions"]


def test_deactivate_user_blocks_login_and_revokes_sessions(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    created = _create(
        api_client,
        auth_headers,
        username="t_disable",
        role_ids=[_role_id(session_factory, "维保工程师")],
    ).json()["data"]
    login = _login(api_client, "t_disable", "Init-passw0rd-1234").json()["data"]

    stopped = api_client.put(
        f"{BASE}/users/{created['id']}", headers=auth_headers, json={"is_active": False}
    )

    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["is_active"] is False
    assert _login(api_client, "t_disable", "Init-passw0rd-1234").status_code in (401, 403)
    # 刷新令牌被撤销，等于强制下线
    refreshed = api_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert refreshed.status_code == 401


def test_reset_password_invalidates_old_one(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    created = _create(
        api_client,
        auth_headers,
        username="t_password",
        role_ids=[_role_id(session_factory, "只读用户")],
    ).json()["data"]

    reset = api_client.post(
        f"{BASE}/users/{created['id']}/password",
        headers=auth_headers,
        json={"password": "New-passw0rd-5678"},
    )

    assert reset.status_code == 200, reset.text
    assert _login(api_client, "t_password", "Init-passw0rd-1234").status_code == 401
    assert _login(api_client, "t_password", "New-passw0rd-5678").status_code == 200


def test_cannot_deactivate_self(
    api_client: TestClient, auth_headers: dict[str, str], test_admin: dict[str, str]
) -> None:
    me = api_client.get("/api/v1/auth/me", headers=auth_headers).json()["data"]

    response = api_client.put(
        f"{BASE}/users/{me['id']}", headers=auth_headers, json={"is_active": False}
    )

    assert response.status_code == 422
    assert "不能停用" in response.json()["message"]


def test_cannot_strip_last_admin_role(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    me = api_client.get("/api/v1/auth/me", headers=auth_headers).json()["data"]

    response = api_client.put(
        f"{BASE}/users/{me['id']}",
        headers=auth_headers,
        json={"role_ids": [_role_id(session_factory, "只读用户")]},
    )

    assert response.status_code == 422
    assert "系统管理员" in response.json()["message"]


# ------------------------------------------------------------------ 角色


def test_custom_role_grants_exactly_its_permissions(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    permissions = api_client.get(f"{BASE}/permissions", headers=auth_headers).json()["data"]["items"]
    equipment_view = next(item for item in permissions if item["code"] == "equipment.view")

    role = api_client.post(
        f"{BASE}/roles",
        headers=auth_headers,
        json={"name": "台账观察员", "description": "只能看设备台账", "permission_ids": [equipment_view["id"]]},
    )
    assert role.status_code == 200, role.text
    role_id = role.json()["data"]["id"]

    _create(api_client, auth_headers, username="t_custom", role_ids=[role_id])
    token = _login(api_client, "t_custom", "Init-passw0rd-1234").json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert api_client.get("/api/v1/equipment", headers=headers).status_code == 200
    assert api_client.get("/api/v1/fault-records", headers=headers).status_code == 403
    assert api_client.get(f"{BASE}/users", headers=headers).status_code == 403


def test_role_editing_and_deletion_rules(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    builtin = _role_id(session_factory, "系统管理员")
    roles = api_client.get(f"{BASE}/roles", headers=auth_headers).json()["data"]["items"]
    builtin_role = next(item for item in roles if item["id"] == builtin)
    permission_ids = builtin_role["permission_ids"][:3]

    # 系统管理员的权限点不允许改
    denied = api_client.put(
        f"{BASE}/roles/{builtin}", headers=auth_headers, json={"permission_ids": permission_ids}
    )
    assert denied.status_code == 422

    # 内置角色不允许删除
    assert api_client.delete(f"{BASE}/roles/{builtin}", headers=auth_headers).status_code == 422

    # 新角色可以改权限、删掉；被账号占用时删不掉
    created = api_client.post(
        f"{BASE}/roles", headers=auth_headers, json={"name": "临时角色-删", "permission_ids": []}
    ).json()["data"]
    updated = api_client.put(
        f"{BASE}/roles/{created['id']}", headers=auth_headers, json={"description": "改过说明"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["description"] == "改过说明"

    _create(api_client, auth_headers, username="t_role_used", role_ids=[created["id"]])
    blocked = api_client.delete(f"{BASE}/roles/{created['id']}", headers=auth_headers)
    assert blocked.status_code == 409

    empty_role = api_client.post(
        f"{BASE}/roles", headers=auth_headers, json={"name": "临时角色-空", "permission_ids": []}
    ).json()["data"]
    assert api_client.delete(f"{BASE}/roles/{empty_role['id']}", headers=auth_headers).status_code == 200


def test_user_changes_are_audited(
    api_client: TestClient, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    _create(
        api_client,
        auth_headers,
        username="t_audit",
        role_ids=[_role_id(session_factory, "只读用户")],
    )

    logs = api_client.get(
        "/api/v1/system/audit-logs",
        headers=auth_headers,
        params={"object_type": "system", "page_size": 20},
    ).json()["data"]["items"]

    assert any(item["action"].endswith("/system/users") for item in logs)
