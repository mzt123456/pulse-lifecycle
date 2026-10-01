"""共享测试夹具：独立测试库、迁移、会话与 API 客户端。

测试库由开发库名追加 _test 得到（pulse_lifecycle_dev_test），可用环境变量
TEST_DATABASE_URL 覆盖；数据库不可达时相关用例整体跳过，不影响其余用例。
"""

import os

# 测试会频繁登录，先把限流阈值调高，避免用例互相干扰；
# 必须写在导入 app 之前，否则配置会被缓存成默认的每分钟 10 次。
# 限流本身由 tests/test_ratelimit.py 单独验证。
os.environ.setdefault("LOGIN_RATE_LIMIT_PER_MINUTE", "1000")

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.seed import seed
from app.db.session import configure_engine, get_db
from app.main import create_app
from app.models.user import Role, User, UserRole

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_ADMIN = {"username": "admin", "password": "Test-passw0rd-1234", "name": "测试管理员"}


def _server_url(url: URL) -> URL:
    """去掉库名的连接串，用于建库与删库（URL.set(database=None) 在 2.1 中不生效）。"""
    return URL.create(
        drivername=url.drivername,
        username=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        query=dict(url.query),
    )


@pytest.fixture(scope="session")
def test_admin() -> dict[str, str]:
    return dict(TEST_ADMIN)


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    settings = get_settings()
    base_url = make_url(os.getenv("TEST_DATABASE_URL") or settings.database_url)
    url = base_url.set(database=f"{base_url.database}_test")

    engine = create_engine(_server_url(url), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            )
            connection.commit()
    except Exception as exc:  # 数据库不可用时跳过，不阻塞其余用例
        pytest.skip(f"测试库不可用，跳过数据库相关用例：{exc}")

    # 注意：str(URL) 会把密码渲染成 ***，必须显式要求明文，否则连接会认证失败
    yield url.render_as_string(hide_password=False)

    with engine.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS `{url.database}`"))
        connection.commit()
    engine.dispose()


@pytest.fixture(scope="session")
def alembic_config(test_database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", test_database_url)
    return config


@pytest.fixture(scope="session")
def migrated(alembic_config: Config, test_database_url: str) -> Iterator[str]:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield test_database_url


@pytest.fixture(scope="session")
def session_factory(migrated: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(migrated, poolclass=NullPool)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    # 审计写入等自建会话的代码也要落到测试库，不能写进开发库
    configure_engine(engine, factory)
    yield factory
    engine.dispose()


@pytest.fixture(scope="session")
def seeded(
    migrated: str, session_factory: sessionmaker[Session], test_admin: dict[str, str]
) -> None:
    with session_factory() as session:
        seed(session, test_admin["username"], test_admin["password"], test_admin["name"])


def _ensure_user(
    session_factory: sessionmaker[Session],
    *,
    username: str,
    password: str,
    real_name: str,
    role_name: str | None = None,
) -> int:
    """确保账号存在（迁移回退用例会清空业务数据，所以每次用到时都确认一次）。"""
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None:
            user = User(
                username=username,
                password_hash=hash_password(password),
                real_name=real_name,
                is_active=True,
            )
            session.add(user)
            session.flush()
            if role_name:
                role = session.execute(select(Role).where(Role.name == role_name)).scalar_one()
                session.add(UserRole(user_id=user.id, role_id=role.id))
            session.commit()
        return user.id


@pytest.fixture
def locked_user(session_factory: sessionmaker[Session]) -> int:
    """建一个专门用来验证锁定的账号。"""
    return _ensure_user(
        session_factory,
        username="lock_test",
        password="lock-test-password",
        real_name="锁定测试",
    )


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """不接数据库的客户端，用于配置与健康检查等用例。"""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def api_client(seeded: None, session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """把数据库依赖指向测试库的客户端，用于接口用例。"""
    app = create_app()

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@pytest.fixture
def auth_headers(
    api_client: TestClient, session_factory: sessionmaker[Session], test_admin: dict[str, str]
) -> dict[str, str]:
    """系统管理员登录后的请求头。"""
    _ensure_user(
        session_factory,
        username=test_admin["username"],
        password=test_admin["password"],
        real_name=test_admin["name"],
        role_name="系统管理员",
    )
    return _login_headers(api_client, test_admin["username"], test_admin["password"])


@pytest.fixture
def readonly_headers(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> dict[str, str]:
    """只读用户登录后的请求头，用于验证权限确实在后端生效。"""
    password = "readonly-password"
    _ensure_user(
        session_factory,
        username="readonly_test",
        password=password,
        real_name="只读测试",
        role_name="只读用户",
    )
    return _login_headers(api_client, "readonly_test", password)
