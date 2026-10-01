"""健康检查接口：供容器探活与外部监控使用。"""

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.response import ApiResponse, ok
from app.db.session import ping_database

router = APIRouter(tags=["系统"])


@router.get("/health", response_model=ApiResponse, summary="健康检查")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """返回应用信息与数据库连通性；数据库不可用时仍然返回 200，由调用方判断。"""
    return ok(
        {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
            "database": "up" if ping_database() else "down",
        }
    )
