"""附件用例：白名单、大小限制、下载与权限。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import BusinessError
from app.models.user import User
from app.services import attachment as service

BASE = "/api/v1/attachments"


def test_upload_and_download_text_file(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    content = "维保记录：本次更换密封圈，油位正常。".encode()
    uploaded = api_client.post(
        BASE,
        headers=auth_headers,
        data={"object_type": "maintenance_order", "object_id": 1},
        files={"file": ("记录.txt", content, "text/plain")},
    )

    assert uploaded.status_code == 200, uploaded.text
    data = uploaded.json()["data"]
    assert data["file_name"] == "记录.txt"
    assert data["size_bytes"] == len(content)
    assert data["object_type"] == "maintenance_order"

    downloaded = api_client.get(f"{BASE}/{data['id']}", headers=auth_headers)
    assert downloaded.status_code == 200
    assert downloaded.content == content

    listed = api_client.get(
        BASE,
        headers=auth_headers,
        params={"object_type": "maintenance_order", "object_id": 1},
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1


def test_upload_rejects_disallowed_extension(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.post(
        BASE,
        headers=auth_headers,
        data={"object_type": "maintenance_order", "object_id": 1},
        files={"file": ("bad.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "不允许的文件类型" in response.json()["message"]


def test_upload_rejects_file_over_size_limit(
    session_factory: sessionmaker[Session],
) -> None:
    """大小限制用一份小限额的配置来验证，避免在测试里造 50 MB 文件。"""
    settings = Settings(_env_file=None, upload_max_size_mb=1)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        with pytest.raises(BusinessError) as exc:
            service.create_attachment(
                session,
                file_name="大文件.txt",
                content=b"x" * (2 * 1024 * 1024),
                content_type="text/plain",
                object_type="maintenance_order",
                object_id=1,
                user=user,
                settings=settings,
            )
    assert exc.value.http_status == 413
    assert "超过限制" in exc.value.message


def test_download_unknown_attachment_returns_404(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.get(f"{BASE}/999999", headers=auth_headers)

    assert response.status_code == 404


def test_readonly_user_can_download_but_not_upload(
    api_client: TestClient, auth_headers: dict[str, str], readonly_headers: dict[str, str]
) -> None:
    uploaded = api_client.post(
        BASE,
        headers=auth_headers,
        data={"object_type": "maintenance_order", "object_id": 2},
        files={"file": ("说明.txt", b"hello", "text/plain")},
    ).json()["data"]

    allowed = api_client.get(f"{BASE}/{uploaded['id']}", headers=readonly_headers)
    assert allowed.status_code == 200

    forbidden = api_client.post(
        BASE,
        headers=readonly_headers,
        data={"object_type": "maintenance_order", "object_id": 2},
        files={"file": ("说明.txt", b"hello", "text/plain")},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 40300
