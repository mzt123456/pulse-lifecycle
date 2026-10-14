"""系统管理接口：审计日志查询，以及用户、角色与权限点的维护（user.manage）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import list_audit_logs
from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.system import AuditLogOut
from app.schemas.user import (
    PasswordReset,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import user as user_service

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/audit-logs", response_model=ApiResponse, summary="审计日志查询")
def query_audit_logs(
    user_id: int | None = Query(default=None, description="按操作人过滤"),
    action: str | None = Query(default=None, description="按动作模糊查询，如 equipment"),
    object_type: str | None = Query(default=None, description="按对象类型过滤"),
    start: datetime | None = Query(default=None, description="起始时间"),
    end: datetime | None = Query(default=None, description="结束时间"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.audit")),
) -> dict:
    items, total = list_audit_logs(
        db,
        user_id=user_id,
        action=action,
        object_type=object_type,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [AuditLogOut.model_validate(item).model_dump(mode="json") for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# ----------------------------------------------------------------- 账号


def _serialize_user(user: User, roles: list[Role]) -> dict:
    return UserOut(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        phone=user.phone,
        department=user.department,
        is_active=user.is_active,
        roles=[role.name for role in roles],
        role_ids=[role.id for role in roles],
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    ).model_dump(mode="json")


@router.get("/users", response_model=ApiResponse, summary="账号列表")
def list_users(
    keyword: str | None = Query(default=None, description="按登录名或姓名模糊查询"),
    is_active: bool | None = Query(default=None, description="只看启用 / 停用"),
    role_id: int | None = Query(default=None, description="按角色过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    items, total = user_service.list_users(
        db, keyword=keyword, is_active=is_active, role_id=role_id, page=page, page_size=page_size
    )
    grouped = user_service.roles_of(db, [item.id for item in items])
    return ok(
        {
            "items": [_serialize_user(item, grouped.get(item.id, [])) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/users/{user_id}", response_model=ApiResponse, summary="账号详情")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    user = user_service.get_user(db, user_id)
    grouped = user_service.roles_of(db, [user.id])
    return ok(_serialize_user(user, grouped.get(user.id, [])))


@router.post("/users", response_model=ApiResponse, summary="新增账号")
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    user = user_service.create_user(
        db,
        username=payload.username,
        password=payload.password,
        real_name=payload.real_name,
        phone=payload.phone,
        department=payload.department,
        role_ids=payload.role_ids,
    )
    grouped = user_service.roles_of(db, [user.id])
    return ok(_serialize_user(user, grouped.get(user.id, [])))


@router.put("/users/{user_id}", response_model=ApiResponse, summary="编辑账号与角色")
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("user.manage")),
) -> dict:
    user = user_service.update_user(
        db,
        user_id,
        actor=actor,
        real_name=payload.real_name,
        phone=payload.phone,
        department=payload.department,
        is_active=payload.is_active,
        role_ids=payload.role_ids,
    )
    grouped = user_service.roles_of(db, [user.id])
    return ok(_serialize_user(user, grouped.get(user.id, [])))


@router.post("/users/{user_id}/password", response_model=ApiResponse, summary="重置口令")
def reset_password(
    user_id: int,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    user = user_service.reset_password(db, user_id, payload.password)
    grouped = user_service.roles_of(db, [user.id])
    return ok(_serialize_user(user, grouped.get(user.id, [])))


# ----------------------------------------------------------------- 角色与权限点


def _serialize_role(role: Role, permission_ids: list[int], user_count: int) -> dict:
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        is_builtin=role.is_builtin,
        permission_ids=permission_ids,
        user_count=user_count,
    ).model_dump(mode="json")


@router.get("/roles", response_model=ApiResponse, summary="角色列表（含权限点）")
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    items = [
        _serialize_role(role, permission_ids, user_count)
        for role, permission_ids, user_count in user_service.list_roles(db)
    ]
    return ok({"items": items, "total": len(items)})


@router.post("/roles", response_model=ApiResponse, summary="新增角色")
def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    role = user_service.create_role(
        db, name=payload.name, description=payload.description, permission_ids=payload.permission_ids
    )
    return ok(_serialize_role(role, sorted(set(payload.permission_ids)), 0))


@router.put("/roles/{role_id}", response_model=ApiResponse, summary="编辑角色的说明与权限点")
def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    user_service.update_role(
        db, role_id, description=payload.description, permission_ids=payload.permission_ids
    )
    matched = next(
        (item for item in user_service.list_roles(db) if item[0].id == role_id),
        None,
    )
    if matched is None:  # pragma: no cover - 刚写完只可能读取到
        raise AssertionError("角色更新后读不到")
    role, permission_ids, user_count = matched
    return ok(_serialize_role(role, permission_ids, user_count))


@router.delete("/roles/{role_id}", response_model=ApiResponse, summary="删除角色")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    user_service.delete_role(db, role_id)
    return ok({"id": role_id, "deleted": True})


@router.get("/permissions", response_model=ApiResponse, summary="权限点清单")
def list_permissions(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user.manage")),
) -> dict:
    items = [
        PermissionOut.model_validate(item).model_dump(mode="json")
        for item in user_service.list_permissions(db)
    ]
    return ok({"items": items, "total": len(items)})
