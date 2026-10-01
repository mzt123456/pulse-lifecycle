"""报表接口：仪表盘汇总、设备利用率、故障分布与使用趋势。"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.services import report as service

router = APIRouter(prefix="/reports", tags=["报表"])


@router.get("/dashboard", response_model=ApiResponse, summary="仪表盘汇总")
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("report.view")),
) -> dict:
    return ok(service.dashboard(db))


@router.get("/equipment-utilization", response_model=ApiResponse, summary="设备利用率统计")
def equipment_utilization(
    start: date | None = Query(default=None, description="起始日期，默认半年前"),
    end: date | None = Query(default=None, description="结束日期，默认今天"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("report.view")),
) -> dict:
    return ok(service.equipment_utilization(db, start, end))


@router.get("/fault-statistics", response_model=ApiResponse, summary="故障统计")
def fault_statistics(
    start: date | None = Query(default=None, description="起始日期，默认半年前"),
    end: date | None = Query(default=None, description="结束日期，默认今天"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("report.view")),
) -> dict:
    return ok(service.fault_statistics(db, start, end))


@router.get("/operation-trend", response_model=ApiResponse, summary="使用趋势")
def operation_trend(
    months: int = Query(default=6, ge=1, le=24, description="统计月数"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("report.view")),
) -> dict:
    return ok(service.operation_trend(db, months))
