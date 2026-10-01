"""v1 版本路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import auth, equipment, health, well_operations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(equipment.router)
api_router.include_router(well_operations.router)
