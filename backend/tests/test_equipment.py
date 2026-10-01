"""设备台账接口用例：编号唯一、乐观锁、状态流水与删除保护。"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.equipment import EquipmentStatusLog

BASE = "/api/v1/equipment"


def test_create_and_get_equipment(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    created = api_client.post(
        BASE,
        headers=auth_headers,
        json={"equipment_no": "PLT-0001", "model": "剪切阀脉冲器 A", "status": "待命"},
    )

    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["equipment_no"] == "PLT-0001"
    assert data["version"] == 1
    assert data["total_run_hours"] == "0.00"
    assert data["total_run_count"] == 0

    detail = api_client.get(f"{BASE}/{data['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["model"] == "剪切阀脉冲器 A"


def test_duplicate_equipment_no_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    payload = {"equipment_no": "PLT-DUP", "status": "待命"}
    assert api_client.post(BASE, headers=auth_headers, json=payload).status_code == 200

    again = api_client.post(BASE, headers=auth_headers, json=payload)

    assert again.status_code == 409
    assert again.json()["code"] == 40900


def test_list_supports_keyword_and_status_filter(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    api_client.post(
        BASE,
        headers=auth_headers,
        json={"equipment_no": "PLT-LIST-1", "model": "过滤型号", "status": "维保"},
    )

    filtered = api_client.get(
        BASE, headers=auth_headers, params={"keyword": "PLT-LIST", "status": "维保"}
    )

    assert filtered.status_code == 200
    body = filtered.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["equipment_no"] == "PLT-LIST-1"


def test_update_requires_matching_version(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = api_client.post(
        BASE, headers=auth_headers, json={"equipment_no": "PLT-VER", "status": "待命"}
    ).json()["data"]

    conflict = api_client.put(
        f"{BASE}/{created['id']}",
        headers=auth_headers,
        json={"version": created["version"] + 5, "model": "改不动"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 40900

    updated = api_client.put(
        f"{BASE}/{created['id']}",
        headers=auth_headers,
        json={"version": created["version"], "model": "改好了", "status": "在用"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == created["version"] + 1
    assert updated.json()["data"]["status"] == "在用"


def test_status_change_writes_log(
    api_client: TestClient,
    auth_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    created = api_client.post(
        BASE, headers=auth_headers, json={"equipment_no": "PLT-LOG", "status": "待命"}
    ).json()["data"]

    api_client.put(
        f"{BASE}/{created['id']}",
        headers=auth_headers,
        json={"version": created["version"], "status": "维保"},
    )

    with session_factory() as session:
        logs = list(
            session.execute(
                select(EquipmentStatusLog)
                .where(EquipmentStatusLog.equipment_id == created["id"])
                .order_by(EquipmentStatusLog.id)
            ).scalars()
        )
    assert [log.to_status for log in logs] == ["待命", "维保"]
    assert logs[1].from_status == "待命"


def test_delete_is_blocked_when_usage_exists(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = api_client.post(
        BASE, headers=auth_headers, json={"equipment_no": "PLT-DEL", "status": "待命"}
    ).json()["data"]
    api_client.post(
        "/api/v1/well-operations",
        headers=auth_headers,
        json={"equipment_id": equipment["id"], "well_no": "井-A"},
    )

    blocked = api_client.delete(f"{BASE}/{equipment['id']}", headers=auth_headers)

    assert blocked.status_code == 409
    assert "使用记录" in blocked.json()["message"]


def test_readonly_user_cannot_create_equipment(
    api_client: TestClient, readonly_headers: dict[str, str]
) -> None:
    forbidden = api_client.post(
        BASE, headers=readonly_headers, json={"equipment_no": "PLT-RO", "status": "待命"}
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 40300

    allowed = api_client.get(BASE, headers=readonly_headers)
    assert allowed.status_code == 200


def test_delete_removes_equipment_with_its_status_log(
    api_client: TestClient,
    auth_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    """只有状态流水的设备可以删除，流水随设备一起清理，不能留下孤儿数据。"""
    created = api_client.post(
        BASE, headers=auth_headers, json={"equipment_no": "PLT-DEL-OK", "status": "待命"}
    ).json()["data"]
    api_client.put(
        f"{BASE}/{created['id']}",
        headers=auth_headers,
        json={"version": created["version"], "status": "维保"},
    )

    deleted = api_client.delete(f"{BASE}/{created['id']}", headers=auth_headers)

    assert deleted.status_code == 200, deleted.text
    assert api_client.get(f"{BASE}/{created['id']}", headers=auth_headers).status_code == 404
    with session_factory() as session:
        remaining = list(
            session.execute(
                select(EquipmentStatusLog).where(
                    EquipmentStatusLog.equipment_id == created["id"]
                )
            ).scalars()
        )
    assert remaining == []


def test_delete_is_blocked_when_maintenance_order_exists(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = api_client.post(
        BASE, headers=auth_headers, json={"equipment_no": "PLT-DEL-MO", "status": "维保"}
    ).json()["data"]
    api_client.post(
        "/api/v1/maintenance-orders",
        headers=auth_headers,
        json={"equipment_id": equipment["id"], "level": "一级维保"},
    )

    blocked = api_client.delete(f"{BASE}/{equipment['id']}", headers=auth_headers)

    assert blocked.status_code == 409
    assert "维保工单" in blocked.json()["message"]
