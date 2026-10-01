"""v1 版本路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import (
    attachments,
    auth,
    consumables,
    dicts,
    equipment,
    faults,
    health,
    maintenance,
    system,
    well_operations,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(equipment.router)
api_router.include_router(well_operations.router)
api_router.include_router(maintenance.router)
api_router.include_router(faults.router)
api_router.include_router(consumables.router)
api_router.include_router(dicts.router)
api_router.include_router(attachments.router)
api_router.include_router(system.router)
