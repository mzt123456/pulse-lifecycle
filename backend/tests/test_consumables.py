"""耗材用例：目录维护、领用扣减、并发不出现负库存与 Excel 导入。"""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

BASE = "/api/v1/consumables"


def _create(client: TestClient, headers: dict[str, str], part_no: str, quantity: int) -> dict:
    response = client.post(
        BASE,
        headers=headers,
        json={"part_no": part_no, "description": f"耗材-{part_no}", "quantity": quantity, "safety_stock": 2},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _xlsx(rows: list[list[object]]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(["部件号", "中文描述", "库存数量", "安全库存", "单位"])
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_create_and_duplicate_part_no(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = _create(api_client, auth_headers, "SP-001", 10)
    assert created["quantity"] == 10

    duplicated = api_client.post(
        BASE,
        headers=auth_headers,
        json={"part_no": "SP-001", "description": "重复部件号", "quantity": 1},
    )

    assert duplicated.status_code == 409
    assert duplicated.json()["code"] == 40900


def test_issue_decrements_stock_and_records_usage(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    item = _create(api_client, auth_headers, "SP-002", 8)

    issued = api_client.post(
        f"{BASE}/usages",
        headers=auth_headers,
        json={"consumable_id": item["id"], "quantity": 3, "remark": "现场更换"},
    )

    assert issued.status_code == 200, issued.text
    usage = issued.json()["data"]
    assert usage["quantity"] == 3
    assert usage["part_no"] == "SP-002"
    assert usage["used_by_name"] == "测试管理员"

    detail = api_client.get(f"{BASE}/{item['id']}", headers=auth_headers).json()["data"]
    assert detail["quantity"] == 5

    usages = api_client.get(
        f"{BASE}/usages", headers=auth_headers, params={"consumable_id": item["id"]}
    ).json()["data"]
    assert usages["total"] == 1


def test_issue_beyond_stock_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    item = _create(api_client, auth_headers, "SP-003", 2)

    rejected = api_client.post(
        f"{BASE}/usages", headers=auth_headers, json={"consumable_id": item["id"], "quantity": 5}
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == 42200
    assert "库存不足" in rejected.json()["message"]
    detail = api_client.get(f"{BASE}/{item['id']}", headers=auth_headers).json()["data"]
    assert detail["quantity"] == 2


def test_concurrent_issue_never_goes_negative(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """库存 5，10 个并发各领 1 件：只能成功 5 次，库存归零且不为负。"""
    item = _create(api_client, auth_headers, "SP-004", 5)

    def issue(_: int):
        return api_client.post(
            f"{BASE}/usages",
            headers=auth_headers,
            json={"consumable_id": item["id"], "quantity": 1},
        )

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(issue, range(10)))

    succeeded = [r for r in responses if r.status_code == 200]
    rejected = [r for r in responses if r.status_code == 422]
    assert len(succeeded) == 5
    assert len(rejected) == 5

    detail = api_client.get(f"{BASE}/{item['id']}", headers=auth_headers).json()["data"]
    assert detail["quantity"] == 0

    usages = api_client.get(
        f"{BASE}/usages", headers=auth_headers, params={"consumable_id": item["id"]}
    ).json()["data"]
    assert usages["total"] == 5


def test_low_stock_filter(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    _create(api_client, auth_headers, "SP-005", 1)

    listed = api_client.get(
        BASE, headers=auth_headers, params={"keyword": "SP-005", "low_stock_only": True}
    )

    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["quantity"] == 1


def test_import_creates_updates_and_reports_errors(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    content = _xlsx(
        [
            ["IMP-1", "导入件一", 10, 2, "个"],
            ["IMP-2", "导入件二", 5, 1, "个"],
            ["", "缺少部件号", 1, 1, "个"],
        ]
    )

    first = api_client.post(
        f"{BASE}/import",
        headers=auth_headers,
        files={"file": ("consumables.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert first.status_code == 200, first.text
    summary = first.json()["data"]
    assert summary["created"] == 2
    assert summary["failed"] == 1
    assert len(summary["errors"]) == 1

    again = api_client.post(
        f"{BASE}/import",
        headers=auth_headers,
        files={
            "file": (
                "consumables.xlsx",
                _xlsx([["IMP-1", "导入件一（改名）", 7, 3, "个"]]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    ).json()["data"]
    assert again["updated"] == 1

    detail = api_client.get(
        BASE, headers=auth_headers, params={"keyword": "IMP-1"}
    ).json()["data"]["items"][0]
    assert detail["description"] == "导入件一（改名）"
    assert detail["quantity"] == 7


def test_import_rejects_missing_columns(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    book = Workbook()
    book.active.append(["部件号", "库存数量"])
    buffer = BytesIO()
    book.save(buffer)

    response = api_client.post(
        f"{BASE}/import",
        headers=auth_headers,
        files={"file": ("bad.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 422
    assert "缺少必需列" in response.json()["message"]
