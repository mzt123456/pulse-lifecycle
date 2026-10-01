"""数据库层验证：迁移建表、重复执行、回退，以及会话的提交与回滚。"""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.db.seed import seed

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


def test_migration_creates_all_tables(migrated: str) -> None:
    assert _table_names(migrated) >= EXPECTED_TABLES


def test_migration_is_repeatable(alembic_config: Config, migrated: str) -> None:
    before = _table_names(migrated)

    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")

    assert _table_names(migrated) == before


def test_migration_downgrade_leaves_empty_schema(
    alembic_config: Config,
    migrated: str,
    session_factory: sessionmaker[Session],
    test_admin: dict[str, str],
) -> None:
    command.downgrade(alembic_config, "base")

    assert _table_names(migrated) == {"alembic_version"}

    command.upgrade(alembic_config, "head")  # 复原，交给后续用例一个已建表的状态
    assert _table_names(migrated) >= EXPECTED_TABLES

    # 回退同时清空了参考数据，这里补回来，避免影响其它用例
    with session_factory() as session:
        seed(session, test_admin["username"], test_admin["password"], test_admin["name"])


def test_session_commits_and_rolls_back(migrated: str) -> None:
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
