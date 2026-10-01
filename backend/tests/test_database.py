"""数据库层验证：迁移建表、重复执行、回退，以及会话的提交与回滚。

测试库由开发库名追加 _test 得到（pulse_lifecycle_dev_test），可用环境变量
TEST_DATABASE_URL 覆盖。数据库服务不可达时跳过，不影响其余用例。
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "attachments",
    "audit_log",
    "backup_records",
    "components",
    "consumable_usages",
    "consumables",
    "dict_items",
    "equipment",
    "equipment_status_log",
    "fault_records",
    "licenses",
    "maintenance_orders",
    "maintenance_steps",
    "measurement_records",
    "permissions",
    "refresh_tokens",
    "role_permissions",
    "roles",
    "user_preferences",
    "user_roles",
    "users",
    "well_operations",
}

INSERT_DICT_ITEM = (
    "INSERT INTO dict_items (category, code, label, sort_order, is_active, created_at, updated_at) "
    "VALUES ('测试', :code, '测试项', 1, 1, NOW(), NOW())"
)


def _table_names(url: str) -> set[str]:
    engine = create_engine(url, poolclass=NullPool)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


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


@pytest.fixture(scope="module")
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
        pytest.skip(f"测试库不可用，跳过数据库层验证：{exc}")

    # 注意：str(URL) 会把密码渲染成 ***，必须显式要求明文，否则连接会认证失败
    yield url.render_as_string(hide_password=False)

    with engine.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS `{url.database}`"))
        connection.commit()
    engine.dispose()


@pytest.fixture(scope="module")
def alembic_config(test_database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", test_database_url)
    return config


@pytest.fixture(scope="module")
def migrated(alembic_config: Config, test_database_url: str) -> Iterator[str]:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield test_database_url


def test_migration_creates_all_tables(migrated: str) -> None:
    assert _table_names(migrated) >= EXPECTED_TABLES


def test_migration_is_repeatable(alembic_config: Config, migrated: str) -> None:
    before = _table_names(migrated)

    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")

    assert _table_names(migrated) == before


def test_migration_downgrade_leaves_empty_schema(
    alembic_config: Config, migrated: str
) -> None:
    command.downgrade(alembic_config, "base")

    assert _table_names(migrated) == {"alembic_version"}

    command.upgrade(alembic_config, "head")  # 复原，交给后续用例一个已建表的状态
    assert _table_names(migrated) >= EXPECTED_TABLES


def test_session_commits_and_rolls_back(alembic_config: Config, migrated: str) -> None:
    command.upgrade(alembic_config, "head")  # 保证表已就位
    engine = create_engine(migrated, poolclass=NullPool)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with factory() as session:  # 提交路径
        session.execute(text(INSERT_DICT_ITEM), {"code": "commit_ok"})
        session.commit()

    session = factory()  # 回滚路径
    try:
        session.execute(text(INSERT_DICT_ITEM), {"code": "rollback_ok"})
        session.rollback()
    finally:
        session.close()

    with engine.connect() as connection:
        codes = set(connection.execute(text("SELECT code FROM dict_items")).scalars())
    engine.dispose()

    assert "commit_ok" in codes
    assert "rollback_ok" not in codes
