"""权限用例：越权拒绝，以及角色权限调整后下次请求即生效。"""

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import Permission, Role, RolePermission

EQUIPMENT = "/api/v1/equipment"


def test_readonly_user_is_blocked_on_every_write_path(
    api_client: TestClient, readonly_headers: dict[str, str]
) -> None:
    """只读用户对五条业务路径的写操作都应被后端拒绝（不是靠前端隐藏按钮）。"""
    attempts = [
        ("post", EQUIPMENT, {"equipment_no": "PLT-PERM-1", "status": "待命"}),
        ("post", "/api/v1/well-operations", {"equipment_id": 1, "well_no": "井-权限"}),
        ("post", "/api/v1/maintenance-orders", {"equipment_id": 1, "level": "一级维保"}),
        ("post", "/api/v1/fault-records", {"equipment_id": 1, "description": "权限测试"}),
        ("post", "/api/v1/consumables", {"part_no": "PERM-1", "description": "权限测试"}),
        ("put", f"{EQUIPMENT}/1", {"version": 1, "model": "改不动"}),
        ("delete", f"{EQUIPMENT}/1", None),
    ]

    for method, url, payload in attempts:
        kwargs: dict = {"headers": readonly_headers}
        if payload is not None:
            kwargs["json"] = payload
        response = getattr(api_client, method)(url, **kwargs)
        assert response.status_code == 403, f"{method.upper()} {url} 应被拒绝"
        assert response.json()["code"] == 40300


def test_permission_change_applies_to_next_request_without_relogin(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    readonly_headers: dict[str, str],
) -> None:
    """给只读角色补一条新增设备权限后，同一个令牌的下一次请求即可通过。"""
    before = api_client.post(
        EQUIPMENT, headers=readonly_headers, json={"equipment_no": "PLT-PERM-2", "status": "待命"}
    )
    assert before.status_code == 403

    with session_factory() as session:
        role = session.execute(select(Role).where(Role.name == "只读用户")).scalar_one()
        permission = session.execute(
            select(Permission).where(Permission.code == "equipment.create")
        ).scalar_one()
        session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        session.commit()

    try:
        after = api_client.post(
            EQUIPMENT,
            headers=readonly_headers,
            json={"equipment_no": "PLT-PERM-2", "status": "待命"},
        )
        assert after.status_code == 200, after.text
        assert after.json()["data"]["equipment_no"] == "PLT-PERM-2"
    finally:
        # 复原角色权限，避免影响其它用例
        with session_factory() as session:
            role = session.execute(select(Role).where(Role.name == "只读用户")).scalar_one()
            permission = session.execute(
                select(Permission).where(Permission.code == "equipment.create")
            ).scalar_one()
            session.execute(
                delete(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            session.commit()
