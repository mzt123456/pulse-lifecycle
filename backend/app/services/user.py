"""用户、角色与权限点的管理逻辑。

业务边界（编写报告 3.1「用户与权限」模块）：

- 账号只停用不删除：业务记录与审计都要能追溯到人；
- 不允许停用自己、也不允许让「系统管理员」这个角色失去最后一个启用账号，
  否则会把管理入口锁死；
- 内置角色的名称与删除不开放（它们的权限范围是业务口径的一部分），
  但说明与权限点可以调整；「系统管理员」固定拥有全部权限，不参与编辑；
- 停用账号或重置口令时，一并撤销该账号未过期的刷新令牌，等于强制下线。
"""

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError, ErrorCode
from app.core.security import hash_password
from app.core.timeutil import local_now
from app.models.user import Permission, RefreshToken, Role, RolePermission, User, UserRole

# 固定拥有全部权限的内置角色
ADMIN_ROLE_NAME = "系统管理员"


# ----------------------------------------------------------------- 查询


def list_users(
    db: Session,
    *,
    keyword: str | None = None,
    is_active: bool | None = None,
    role_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    stmt = select(User)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(User.username.like(pattern), User.real_name.like(pattern)))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if role_id is not None:
        stmt = stmt.where(User.id.in_(select(UserRole.user_id).where(UserRole.role_id == role_id)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.execute(
            stmt.order_by(User.id).limit(page_size).offset((page - 1) * page_size)
        ).scalars()
    )
    return items, total


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "账号不存在", 404)
    return user


def roles_of(db: Session, user_ids: list[int]) -> dict[int, list[Role]]:
    """批量取用户角色，避免列表页逐行查询。"""
    if not user_ids:
        return {}
    rows = db.execute(
        select(UserRole.user_id, Role)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(user_ids))
        .order_by(Role.id)
    ).all()
    grouped: dict[int, list[Role]] = {}
    for user_id, role in rows:
        grouped.setdefault(user_id, []).append(role)
    return grouped


def list_roles(db: Session) -> list[tuple[Role, list[int], int]]:
    """返回（角色, 权限点 ID, 关联账号数）。"""
    roles = list(db.execute(select(Role).order_by(Role.id)).scalars())
    permission_map: dict[int, list[int]] = {}
    for role_id, permission_id in db.execute(
        select(RolePermission.role_id, RolePermission.permission_id)
    ).all():
        permission_map.setdefault(role_id, []).append(permission_id)
    user_counts = dict(
        db.execute(
            select(UserRole.role_id, func.count(UserRole.user_id)).group_by(UserRole.role_id)
        ).all()
    )
    return [
        (role, sorted(permission_map.get(role.id, [])), user_counts.get(role.id, 0)) for role in roles
    ]


def list_permissions(db: Session) -> list[Permission]:
    return list(db.execute(select(Permission).order_by(Permission.module, Permission.action)).scalars())


# ----------------------------------------------------------------- 内部校验


def _ensure_username_free(db: Session, username: str, *, exclude_id: int | None = None) -> None:
    stmt = select(User.id).where(User.username == username)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise BusinessError(ErrorCode.CONFLICT, f"登录名 {username} 已被占用", 409)


def _resolve_roles(db: Session, role_ids: list[int]) -> list[Role]:
    unique_ids = sorted(set(role_ids))
    roles = list(db.execute(select(Role).where(Role.id.in_(unique_ids))).scalars())
    missing = set(unique_ids) - {role.id for role in roles}
    if missing:
        raise BusinessError(ErrorCode.BUSINESS_RULE, f"角色不存在：{sorted(missing)}", 422)
    return roles


def _resolve_permissions(db: Session, permission_ids: list[int]) -> list[Permission]:
    unique_ids = sorted(set(permission_ids))
    if not unique_ids:
        return []
    permissions = list(
        db.execute(select(Permission).where(Permission.id.in_(unique_ids))).scalars()
    )
    missing = set(unique_ids) - {item.id for item in permissions}
    if missing:
        raise BusinessError(ErrorCode.BUSINESS_RULE, f"权限点不存在：{sorted(missing)}", 422)
    return permissions


def _replace_roles(db: Session, user: User, role_ids: list[int]) -> None:
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role in _resolve_roles(db, role_ids):
        db.add(UserRole(user_id=user.id, role_id=role.id))


def _revoke_tokens(db: Session, user_id: int) -> None:
    """强制下线：把该账号未过期的刷新令牌全部标记撤销。"""
    db.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > local_now(),
        )
    )


def _holds_admin_role(db: Session, user_id: int) -> bool:
    return (
        db.scalar(
            select(UserRole.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.name == ADMIN_ROLE_NAME)
        )
        is not None
    )


def _ensure_admin_remains(db: Session, *, exclude_user_id: int) -> None:
    """除 exclude_user_id 外，仍要有一个启用的系统管理员。"""
    remaining = db.scalar(
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == ADMIN_ROLE_NAME, User.is_active.is_(True), User.id != exclude_user_id)
    )
    if not remaining:
        raise BusinessError(
            ErrorCode.BUSINESS_RULE, "至少保留一个启用的系统管理员账号", 422
        )


# ----------------------------------------------------------------- 账号写入


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    real_name: str,
    phone: str | None = None,
    department: str | None = None,
    role_ids: list[int],
) -> User:
    _ensure_username_free(db, username)
    user = User(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        phone=phone,
        department=department,
        is_active=True,
    )
    db.add(user)
    db.flush()
    _replace_roles(db, user, role_ids)
    db.flush()
    return user


def update_user(
    db: Session,
    user_id: int,
    *,
    actor: User,
    real_name: str | None = None,
    phone: str | None = None,
    department: str | None = None,
    is_active: bool | None = None,
    role_ids: list[int] | None = None,
) -> User:
    user = get_user(db, user_id)

    if real_name is not None:
        user.real_name = real_name
    if phone is not None:
        user.phone = phone
    if department is not None:
        user.department = department

    if is_active is not None and is_active != user.is_active:
        if not is_active and user.id == actor.id:
            raise BusinessError(ErrorCode.BUSINESS_RULE, "不能停用当前登录的账号", 422)
        if not is_active and _holds_admin_role(db, user.id):
            _ensure_admin_remains(db, exclude_user_id=user.id)
        user.is_active = is_active
        if not is_active:
            _revoke_tokens(db, user.id)

    if role_ids is not None:
        was_admin = _holds_admin_role(db, user.id)
        roles = _resolve_roles(db, role_ids)
        will_be_admin = any(role.name == ADMIN_ROLE_NAME for role in roles)
        if was_admin and not will_be_admin:
            _ensure_admin_remains(db, exclude_user_id=user.id)
        _replace_roles(db, user, [role.id for role in roles])

    db.flush()
    return user


def reset_password(db: Session, user_id: int, password: str) -> User:
    user = get_user(db, user_id)
    user.password_hash = hash_password(password)
    user.failed_attempts = 0
    user.locked_until = None
    _revoke_tokens(db, user.id)  # 改口令后旧会话立即失效
    db.flush()
    return user


# ----------------------------------------------------------------- 角色写入


def create_role(
    db: Session,
    *,
    name: str,
    description: str | None = None,
    permission_ids: list[int],
) -> Role:
    if db.scalar(select(Role.id).where(Role.name == name)) is not None:
        raise BusinessError(ErrorCode.CONFLICT, f"角色 {name} 已存在", 409)
    role = Role(name=name, description=description, is_builtin=False)
    db.add(role)
    db.flush()
    _replace_permissions(db, role, permission_ids)
    db.flush()
    return role


def update_role(
    db: Session,
    role_id: int,
    *,
    description: str | None = None,
    permission_ids: list[int] | None = None,
) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "角色不存在", 404)
    if description is not None:
        role.description = description
    if role.name == ADMIN_ROLE_NAME and permission_ids is not None:
        raise BusinessError(
            ErrorCode.BUSINESS_RULE, "系统管理员固定拥有全部权限，不支持修改", 422
        )
    if permission_ids is not None:
        _replace_permissions(db, role, permission_ids)
    db.flush()
    return role


def _replace_permissions(db: Session, role: Role, permission_ids: list[int]) -> None:
    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for permission in _resolve_permissions(db, permission_ids):
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))


def delete_role(db: Session, role_id: int) -> None:
    role = db.get(Role, role_id)
    if role is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "角色不存在", 404)
    if role.is_builtin:
        raise BusinessError(ErrorCode.BUSINESS_RULE, "内置角色不允许删除", 422)
    used = db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)) or 0
    if used:
        raise BusinessError(
            ErrorCode.CONFLICT, f"该角色已分配给 {used} 个账号，请先调整这些账号的角色", 409
        )
    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    db.delete(role)
    db.flush()
