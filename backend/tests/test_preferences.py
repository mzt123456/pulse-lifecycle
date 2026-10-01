"""用户偏好用例：默认值、保存与按用户隔离。"""

from fastapi.testclient import TestClient

BASE = "/api/v1/user-preferences"


def test_defaults_then_save(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    initial = api_client.get(BASE, headers=auth_headers)
    assert initial.status_code == 200, initial.text
    data = initial.json()["data"]
    assert data["page_size"] == 20
    assert data["nav_collapsed"] is False
    assert data["table_columns"] == {}

    saved = api_client.put(
        BASE,
        headers=auth_headers,
        json={
            "page_size": 50,
            "nav_collapsed": True,
            "table_columns": {"well_operations": ["equipment_no", "well_no", "run_hours"]},
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["page_size"] == 50

    reloaded = api_client.get(BASE, headers=auth_headers).json()["data"]
    assert reloaded["page_size"] == 50
    assert reloaded["nav_collapsed"] is True
    assert reloaded["table_columns"]["well_operations"] == [
        "equipment_no",
        "well_no",
        "run_hours",
    ]


def test_partial_update_keeps_other_fields(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    api_client.put(BASE, headers=auth_headers, json={"page_size": 100, "nav_collapsed": True})

    api_client.put(BASE, headers=auth_headers, json={"nav_collapsed": False})

    data = api_client.get(BASE, headers=auth_headers).json()["data"]
    assert data["page_size"] == 100  # 未提交的字段保持原值
    assert data["nav_collapsed"] is False


def test_preferences_are_per_user(
    api_client: TestClient, auth_headers: dict[str, str], readonly_headers: dict[str, str]
) -> None:
    api_client.put(BASE, headers=auth_headers, json={"page_size": 50})

    readonly_view = api_client.get(BASE, headers=readonly_headers).json()["data"]

    assert readonly_view["page_size"] == 20


def test_preferences_require_login(api_client: TestClient) -> None:
    response = api_client.get(BASE)

    assert response.status_code == 401
    assert response.json()["code"] == 40100
