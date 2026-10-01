"""初始化基础数据：权限点、内置角色与初始管理员。可重复执行。

用法：在 backend 目录下执行 python -m app.db.seed
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_session_factory
from app.models.user import Permission, Role, RolePermission, User, UserRole

# 权限点按“模块 + 操作”定义，对应编写报告 3.2 的模块与 5.3 的接口清单
PERMISSIONS: list[tuple[str, str, str, str]] = [
    ("equipment.view", "equipment", "view", "查看设备台账"),
    ("equipment.create", "equipment", "create", "新增设备"),
    ("equipment.update", "equipment", "update", "编辑设备"),
    ("equipment.delete", "equipment", "delete", "删除设备"),
    ("well_operation.view", "well_operation", "view", "查看使用记录"),
    ("well_operation.create", "well_operation", "create", "新增使用记录"),
    ("well_operation.update", "well_operation", "update", "编辑使用记录"),
    ("well_operation.delete", "well_operation", "delete", "删除使用记录"),
    ("well_operation.export", "well_operation", "export", "导出使用记录"),
    ("maintenance.view", "maintenance", "view", "查看维保工单"),
    ("maintenance.create", "maintenance", "create", "创建维保工单"),
    ("maintenance.update", "maintenance", "update", "更新维保工单"),
    ("maintenance.export", "maintenance", "export", "导出维保报告"),
    ("fault.view", "fault", "view", "查看故障记录"),
    ("fault.create", "fault", "create", "新增故障记录"),
    ("fault.update", "fault", "update", "处理故障记录"),
    ("consumable.view", "consumable", "view", "查看耗材"),
    ("consumable.create", "consumable", "create", "维护耗材目录"),
    ("consumable.import", "consumable", "import", "批量导入耗材"),
    ("consumable.issue", "consumable", "issue", "领用耗材"),
    ("report.view", "report", "view", "查看报表"),
    ("report.export", "report", "export", "导出报表"),
    ("attachments.upload", "attachments", "upload", "上传附件"),
    ("attachments.download", "attachments", "download", "下载附件"),
    ("system.settings", "system", "settings", "参数配置"),
    ("system.audit", "system", "audit", "查看审计日志"),
    ("system.backup", "system", "backup", "数据备份"),
    ("user.manage", "user", "manage", "用户与权限管理"),
]

# 内置角色与默认权限范围，取值来自编写报告 3.2 的对应关系表；None 表示全部权限
ROLE_PERMISSIONS: dict[str, list[str] | None] = {
    "系统管理员": None,
    "维保工程师": [
        "equipment.view",
        "equipment.update",
        "well_operation.view",
        "well_operation.update",
        "maintenance.view",
        "maintenance.create",
        "maintenance.update",
        "maintenance.export",
        "fault.view",
        "fault.create",
        "fault.update",
        "consumable.view",
        "consumable.issue",
        "report.view",
        "report.export",
        "attachments.upload",
        "attachments.download",
    ],
    "现场技术员": [
        "equipment.view",
        "well_operation.view",
        "well_operation.create",
        "maintenance.view",
        "fault.view",
        "fault.create",
        "consumable.view",
        "report.view",
        "attachments.upload",
        "attachments.download",
    ],
    "只读用户": [
        "equipment.view",
        "well_operation.view",
        "maintenance.view",
        "fault.view",
        "report.view",
        "attachments.download",
    ],
}


def seed(db: Session, admin_username: str, admin_password: str, admin_name: str) -> dict[str, int]:
    """写入权限点、内置角色与初始管理员；已存在的不重复创建。"""
    summary = {"permissions_created": 0, "roles_created": 0, "admin_created": 0}

    permission_by_code: dict[str, Permission] = {}
    for code, module, action, description in PERMISSIONS:
        item = db.execute(select(Permission).where(Permission.code == code)).scalar_one_or_none()
        if item is None:
            item = Permission(code=code, module=module, action=action, description=description)
            db.add(item)
            db.flush()
            summary["permissions_created"] += 1
        permission_by_code[code] = item

    role_by_name: dict[str, Role] = {}
    for name, codes in ROLE_PERMISSIONS.items():
        role = db.execute(select(Role).where(Role.name == name)).scalar_one_or_none()
        if role is None:
            role = Role(name=name, description=f"{name}（内置角色）", is_builtin=True)
            db.add(role)
            db.flush()
            summary["roles_created"] += 1
        role_by_name[name] = role

        wanted = codes if codes is not None else list(permission_by_code)
        existing = set(
            db.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            ).scalars()
        )
        for code in wanted:
            if code in existing:
                continue
            db.add(RolePermission(role_id=role.id, permission_id=permission_by_code[code].id))

    admin = db.execute(select(User).where(User.username == admin_username)).scalar_one_or_none()
    if admin is None:
        if not admin_password:
            raise ValueError("初始管理员口令为空，请先在 .env 里设置 INITIAL_ADMIN_PASSWORD")
        admin = User(
            username=admin_username,
            password_hash=hash_password(admin_password),
            real_name=admin_name,
            department="系统管理",
            is_active=True,
        )
        db.add(admin)
        db.flush()
        db.add(UserRole(user_id=admin.id, role_id=role_by_name["系统管理员"].id))
        summary["admin_created"] = 1

    db.commit()
    return summary


def main() -> None:
    settings = get_settings()
    if not settings.initial_admin_password:
        raise SystemExit("请先在 backend/.env 里设置 INITIAL_ADMIN_PASSWORD，再执行种子脚本")

    session = get_session_factory()()
    try:
        summary = seed(
            session,
            settings.initial_admin_username,
            settings.initial_admin_password,
            settings.initial_admin_name,
        )
    finally:
        session.close()
    print("种子数据完成：", summary)


if __name__ == "__main__":
    main()
