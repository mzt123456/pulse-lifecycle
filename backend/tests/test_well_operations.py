"""使用记录接口用例：自动计算、台账同步与删除回退。"""

from fastapi.testclient import TestClient

EQUIPMENT = "/api/v1/equipment"
BASE = "/api/v1/well-operations"


def _create_equipment(client: TestClient, headers: dict[str, str], no: str) -> dict:
    response = client.post(EQUIPMENT, headers=headers, json={"equipment_no": no, "status": "在用"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _get_equipment(client: TestClient, headers: dict[str, str], equipment_id: int) -> dict:
    return client.get(f"{EQUIPMENT}/{equipment_id}", headers=headers).json()["data"]


def test_create_computes_run_hours_footage_and_updates_totals(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-WO-1")

    created = api_client.post(
        BASE,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "well_no": "井-100",
            "well_depth": "3200.50",
            "start_date": "2026-09-01 08:00:00",
            "end_date": "2026-09-01 11:30:00",
            "run_in_depth": "3100.00",
            "run_out_depth": "3300.00",
            "mud_density": "1.250",
        },
    )

    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["run_hours"] == "3.50"
    assert data["footage"] == "200.00"
    assert data["well_depth"] == "3200.50"
    assert data["mud_density"] == "1.250"
    assert data["equipment_no"] == "PLT-WO-1"

    updated_equipment = _get_equipment(api_client, auth_headers, equipment["id"])
    assert updated_equipment["total_run_hours"] == "3.50"
    assert updated_equipment["total_run_count"] == 1


def test_manual_values_take_precedence(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-WO-2")

    created = api_client.post(
        BASE,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "start_date": "2026-09-02 08:00:00",
            "end_date": "2026-09-02 10:00:00",
            "run_hours": "5.25",
            "run_in_depth": "100.00",
            "run_out_depth": "120.00",
            "footage": "19.50",
        },
    ).json()["data"]

    assert created["run_hours"] == "5.25"
    assert created["footage"] == "19.50"
    assert _get_equipment(api_client, auth_headers, equipment["id"])["total_run_hours"] == "5.25"


def test_update_adjusts_equipment_totals_by_delta(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-WO-3")
    created = api_client.post(
        BASE,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "start_date": "2026-09-03 08:00:00",
            "end_date": "2026-09-03 10:00:00",
        },
    ).json()["data"]
    assert created["run_hours"] == "2.00"

    updated = api_client.put(
        f"{BASE}/{created['id']}",
        headers=auth_headers,
        json={"end_date": "2026-09-03 09:00:00"},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["run_hours"] == "1.00"
    assert _get_equipment(api_client, auth_headers, equipment["id"])["total_run_hours"] == "1.00"


def test_delete_rolls_back_equipment_totals(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-WO-4")
    created = api_client.post(
        BASE,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "start_date": "2026-09-04 08:00:00",
            "end_date": "2026-09-04 12:00:00",
        },
    ).json()["data"]

    deleted = api_client.delete(f"{BASE}/{created['id']}", headers=auth_headers)

    assert deleted.status_code == 200
    after = _get_equipment(api_client, auth_headers, equipment["id"])
    assert after["total_run_hours"] == "0.00"
    assert after["total_run_count"] == 0
    assert api_client.get(f"{BASE}/{created['id']}", headers=auth_headers).status_code == 404


def test_create_with_unknown_equipment_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.post(
        BASE, headers=auth_headers, json={"equipment_id": 999999, "well_no": "井-X"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_list_filters_by_equipment(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    equipment = _create_equipment(api_client, auth_headers, "PLT-WO-5")
    api_client.post(
        BASE,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "well_no": "井-FILTER",
            "start_date": "2026-09-05 08:00:00",
            "end_date": "2026-09-05 09:00:00",
        },
    )

    listed = api_client.get(BASE, headers=auth_headers, params={"equipment_id": equipment["id"]})

    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["well_no"] == "井-FILTER"
