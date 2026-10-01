"""维保工单用例：步骤清单生成、工单号规则、步骤勾选与完成后刷新设备维保时间。"""

import re
from datetime import date

from fastapi.testclient import TestClient

EQUIPMENT = "/api/v1/equipment"
BASE = "/api/v1/maintenance-orders"


def _create_equipment(client: TestClient, headers: dict[str, str], no: str) -> dict:
    response = client.post(EQUIPMENT, headers=headers, json={"equipment_no": no, "status": "维保"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _create_order(
    client: TestClient, headers: dict[str, str], equipment_id: int, level: str
) -> dict:
    response = client.post(
        BASE, headers=headers, json={"equipment_id": equipment_id, "level": level}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_create_order_generates_number_and_steps(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-1")

    order = _create_order(api_client, auth_headers, equipment["id"], "一级维保")

    assert re.fullmatch(rf"WX{date.today():%Y%m%d}\d{{3}}", order["order_no"])
    assert order["status"] == "进行中"
    assert order["equipment_no"] == "PLT-MO-1"
    assert [step["name"] for step in order["steps"]] == [
        "外观检查",
        "油位测量",
        "密封性检查",
        "连接紧固",
        "功能测试",
    ]
    assert [step["seq"] for step in order["steps"]] == [1, 2, 3, 4, 5]
    assert all(step["is_done"] is False for step in order["steps"])


def test_step_counts_follow_level(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-2")

    expected = {"一级维保": 5, "二级维保": 10, "三级维保": 16, "四级维保": 23}
    for level, count in expected.items():
        order = _create_order(api_client, auth_headers, equipment["id"], level)
        assert len(order["steps"]) == count, f"{level} 步骤数应为 {count}"
        assert order["steps"][0]["name"] == "外观检查"

    four_level = _create_order(api_client, auth_headers, equipment["id"], "四级维保")
    assert four_level["steps"][-1]["name"] == "出厂验收"


def test_order_numbers_increase_within_the_day(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-3")

    first = _create_order(api_client, auth_headers, equipment["id"], "一级维保")
    second = _create_order(api_client, auth_headers, equipment["id"], "一级维保")

    assert first["order_no"] != second["order_no"]
    assert int(second["order_no"][-3:]) == int(first["order_no"][-3:]) + 1


def test_invalid_level_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-4")

    response = api_client.post(
        BASE, headers=auth_headers, json={"equipment_id": equipment["id"], "level": "五级维保"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_complete_step_records_person_and_time(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-5")
    order = _create_order(api_client, auth_headers, equipment["id"], "二级维保")
    step = order["steps"][0]

    completed = api_client.post(
        f"{BASE}/{order['id']}/steps/{step['id']}",
        headers=auth_headers,
        json={"is_done": True, "remark": "已检查，无异常"},
    )

    assert completed.status_code == 200, completed.text
    data = completed.json()["data"]
    assert data["is_done"] is True
    assert data["done_by"] is not None
    assert data["done_by_name"] == "测试管理员"
    assert data["done_at"] is not None
    assert data["remark"] == "已检查，无异常"

    detail = api_client.get(f"{BASE}/{order['id']}", headers=auth_headers).json()["data"]
    assert detail["steps"][0]["is_done"] is True


def test_unchecking_step_clears_completion(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-6")
    order = _create_order(api_client, auth_headers, equipment["id"], "一级维保")
    step = order["steps"][0]

    api_client.post(
        f"{BASE}/{order['id']}/steps/{step['id']}", headers=auth_headers, json={"is_done": True}
    )
    undone = api_client.post(
        f"{BASE}/{order['id']}/steps/{step['id']}", headers=auth_headers, json={"is_done": False}
    ).json()["data"]

    assert undone["is_done"] is False
    assert undone["done_by"] is None
    assert undone["done_at"] is None


def test_step_from_another_order_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-7")
    first = _create_order(api_client, auth_headers, equipment["id"], "一级维保")
    second = _create_order(api_client, auth_headers, equipment["id"], "一级维保")

    response = api_client.post(
        f"{BASE}/{first['id']}/steps/{second['steps'][0]['id']}",
        headers=auth_headers,
        json={"is_done": True},
    )

    assert response.status_code == 404


def test_change_level_rebuilds_steps(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-8")
    order = _create_order(api_client, auth_headers, equipment["id"], "一级维保")

    updated = api_client.put(
        f"{BASE}/{order['id']}", headers=auth_headers, json={"level": "三级维保"}
    )

    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["level"] == "三级维保"
    assert len(data["steps"]) == 16
    assert [step["name"] for step in data["steps"][:5]] == [
        "外观检查",
        "油位测量",
        "密封性检查",
        "连接紧固",
        "功能测试",
    ]
    assert data["steps"][5]["name"] == "油液更换"
    assert data["steps"][-1]["name"] == "出厂测试"


def test_completing_order_updates_equipment_maintenance_time(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-9")
    order = _create_order(api_client, auth_headers, equipment["id"], "一级维保")
    assert equipment["last_maintenance_at"] is None

    finished = api_client.put(
        f"{BASE}/{order['id']}",
        headers=auth_headers,
        json={"status": "已完成", "result": "合格", "oil_level": "26.50", "suggestion": "三个月后复查"},
    )

    assert finished.status_code == 200, finished.text
    data = finished.json()["data"]
    assert data["status"] == "已完成"
    assert data["end_date"] == date.today().isoformat()
    assert data["oil_level"] == "26.50"

    refreshed = api_client.get(f"{EQUIPMENT}/{equipment['id']}", headers=auth_headers).json()["data"]
    assert refreshed["last_maintenance_at"] is not None


def test_list_filters_by_status(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-10")
    order = _create_order(api_client, auth_headers, equipment["id"], "一级维保")
    api_client.put(f"{BASE}/{order['id']}", headers=auth_headers, json={"status": "已完成"})

    listed = api_client.get(
        BASE, headers=auth_headers, params={"equipment_id": equipment["id"], "status": "已完成"}
    )

    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["order_no"] == order["order_no"]
    assert "steps" not in body["items"][0]


def test_readonly_user_cannot_create_order(
    api_client: TestClient, auth_headers: dict[str, str], readonly_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-MO-11")

    forbidden = api_client.post(
        BASE,
        headers=readonly_headers,
        json={"equipment_id": equipment["id"], "level": "一级维保"},
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 40300
