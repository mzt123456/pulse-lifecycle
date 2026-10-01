"""故障记录用例：字典校验、状态流转与筛选。"""

from fastapi.testclient import TestClient

EQUIPMENT = "/api/v1/equipment"
BASE = "/api/v1/fault-records"


def _create_equipment(client: TestClient, headers: dict[str, str], no: str) -> dict:
    response = client.post(EQUIPMENT, headers=headers, json={"equipment_no": no, "status": "在用"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_create_and_update_fault(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-FR-1")

    created = api_client.post(
        BASE,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "occurred_at": "2026-09-25 10:30:00",
            "position": "阀总成",
            "fault_type": "密封失效",
            "description": "下井后压力异常",
        },
    )

    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["status"] == "待处理"
    assert data["equipment_no"] == "PLT-FR-1"

    handled = api_client.put(
        f"{BASE}/{data['id']}",
        headers=auth_headers,
        json={"cause": "密封圈老化", "solution": "更换密封圈", "status": "已解决"},
    )

    assert handled.status_code == 200
    updated = handled.json()["data"]
    assert updated["status"] == "已解决"
    assert updated["cause"] == "密封圈老化"


def test_invalid_fault_type_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-FR-2")

    response = api_client.post(
        BASE,
        headers=auth_headers,
        json={"equipment_id": equipment["id"], "fault_type": "不存在的类型"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == 42200
    assert "故障类型" in response.json()["message"]


def test_list_filters_by_equipment_and_status(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-FR-3")
    created = api_client.post(
        BASE,
        headers=auth_headers,
        json={"equipment_id": equipment["id"], "fault_type": "电气故障", "status": "处理中"},
    ).json()["data"]

    listed = api_client.get(
        BASE,
        headers=auth_headers,
        params={"equipment_id": equipment["id"], "status": "处理中"},
    )

    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]


def test_unknown_equipment_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.post(
        BASE, headers=auth_headers, json={"equipment_id": 999999, "description": "无设备"}
    )

    assert response.status_code == 404


def test_readonly_user_cannot_create_fault(
    api_client: TestClient, auth_headers: dict[str, str], readonly_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-FR-4")

    forbidden = api_client.post(
        BASE,
        headers=readonly_headers,
        json={"equipment_id": equipment["id"], "description": "只读用户不能新增"},
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 40300
