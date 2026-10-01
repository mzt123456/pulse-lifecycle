"""审计日志用例：登录留痕、业务写操作留痕、只读与权限。"""

from fastapi.testclient import TestClient

LOGIN = "/api/v1/auth/login"
AUDIT = "/api/v1/system/audit-logs"


def _audits(api_client: TestClient, headers: dict[str, str], **params) -> dict:
    response = api_client.get(AUDIT, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_login_success_is_recorded(
    api_client: TestClient, auth_headers: dict[str, str], test_admin: dict[str, str]
) -> None:
    data = _audits(api_client, auth_headers, action="login", page_size=50)

    entries = [item for item in data["items"] if item["username"] == test_admin["username"]]
    assert entries, "登录成功应留下审计记录"
    assert any("success" in (item["detail"] or "") for item in entries)
    assert entries[0]["client_ip"]


def test_login_failure_is_recorded(
    api_client: TestClient, auth_headers: dict[str, str], test_admin: dict[str, str]
) -> None:
    api_client.post(LOGIN, json={"username": test_admin["username"], "password": "错误口令"})

    data = _audits(api_client, auth_headers, action="login", page_size=50)

    assert any("口令错误" in (item["detail"] or "") for item in data["items"])


def test_business_write_is_recorded(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    created = api_client.post(
        "/api/v1/equipment",
        headers=auth_headers,
        json={"equipment_no": "PLT-AUDIT-1", "status": "待命"},
    )
    assert created.status_code == 200

    data = _audits(api_client, auth_headers, action="equipment", page_size=50)

    entries = [item for item in data["items"] if item["action"].endswith("/equipment")]
    assert entries, "新增设备应留下审计记录"
    assert entries[0]["object_type"] == "equipment"
    assert entries[0]["user_id"] is not None
    assert '"status": 200' in (entries[0]["detail"] or "")


def test_audit_log_is_append_only(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """审计日志只提供查询：没有修改与删除接口。"""
    assert api_client.put(f"{AUDIT}/1", headers=auth_headers, json={}).status_code in (404, 405)
    assert api_client.delete(f"{AUDIT}/1", headers=auth_headers).status_code in (404, 405)
    assert api_client.post(AUDIT, headers=auth_headers, json={}).status_code == 405


def test_readonly_user_cannot_query_audit_log(
    api_client: TestClient, readonly_headers: dict[str, str]
) -> None:
    response = api_client.get(AUDIT, headers=readonly_headers)

    assert response.status_code == 403
    assert response.json()["code"] == 40300
