"""系统管理接口：目前提供审计日志查询。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import list_audit_logs
from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.system import AuditLogOut

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
