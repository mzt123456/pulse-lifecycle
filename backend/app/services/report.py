"""报表与统计：仪表盘汇总、设备利用率、故障分布与使用趋势。

统计口径按编写报告第十一章与业务约定实现，前端页面上会写明公式，
便于使用岗位核对；口径如调整，只改这里并同步文档。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.timeutil import local_now
from app.models.consumable import Consumable
from app.models.equipment import Equipment
from app.models.fault import FaultRecord
from app.models.maintenance import MaintenanceOrder
from app.models.operation import WellOperation


def dashboard(db: Session, settings: Settings | None = None) -> dict:
    """仪表盘汇总：设备规模与状态分布、最近维保与使用记录、待关注项。"""
    settings = settings or get_settings()

    total = db.scalar(select(func.count()).select_from(Equipment)) or 0
    status_rows = db.execute(
        select(Equipment.status, func.count()).group_by(Equipment.status)
    ).all()
    status_counts = {status: count for status, count in status_rows}

    recent_orders = list(
        db.execute(
            select(MaintenanceOrder)
            .order_by(MaintenanceOrder.id.desc())
            .limit(5)
        )
        .unique()
        .scalars()
    )
    recent_operations = list(
        db.execute(
            select(WellOperation).order_by(WellOperation.id.desc()).limit(5)
        )
        .unique()
        .scalars()
    )

    # 待关注：超过 500 小时未维保的设备、低于安全库存的耗材
    threshold = local_now() - timedelta(days=settings.maint_interval_days)
    maintenance_due = (
        db.scalar(
            select(func.count())
            .select_from(Equipment)
            .where(
                Equipment.status != "报废",
                Equipment.total_run_hours >= settings.maint_interval_hours,
                (Equipment.last_maintenance_at.is_(None)) | (Equipment.last_maintenance_at <= threshold),
            )
        )
        or 0
    )
    low_stock = (
        db.scalar(
            select(func.count())
            .select_from(Consumable)
            .where(Consumable.quantity <= Consumable.safety_stock)
        )
        or 0
    )
    open_faults = (
        db.scalar(
            select(func.count()).select_from(FaultRecord).where(FaultRecord.status != "已解决")
        )
        or 0
    )

    return {
        "equipment_total": total,
        "status_counts": status_counts,
        "maintenance_due": maintenance_due,
        "low_stock_consumables": low_stock,
        "open_faults": open_faults,
        "recent_maintenance": [
            {
                "order_no": order.order_no,
                "equipment_no": order.equipment_no,
                "level": order.level,
                "status": order.status,
                "start_date": order.start_date.isoformat() if order.start_date else None,
            }
            for order in recent_orders
        ],
        "recent_operations": [
            {
                "equipment_no": operation.equipment_no,
                "well_no": operation.well_no,
                "run_hours": format(operation.run_hours, "f") if operation.run_hours is not None else None,
                "start_date": operation.start_date.strftime("%Y-%m-%d %H:%M:%S")
                if operation.start_date
                else None,
            }
            for operation in recent_operations
        ],
    }


def _range(start: date | None, end: date | None, default_days: int = 180) -> tuple[datetime, datetime]:
    end_date = end or local_now().date()
    start_date = start or (end_date - timedelta(days=default_days))
    return (
        datetime.combine(start_date, datetime.min.time()),
        datetime.combine(end_date, datetime.max.time()),
    )


def equipment_utilization(
    db: Session, start: date | None = None, end: date | None = None
) -> dict:
    """设备利用率：区间内使用时长 ÷ 区间总小时数，按设备列出。

    口径说明：区间总小时数 = 天数 × 24；使用时长取该区间内使用记录之和。
    """
    start_at, end_at = _range(start, end)
    total_hours = Decimal(str((end_at - start_at).total_seconds() / 3600)).quantize(Decimal("0.01"))

    rows = db.execute(
        select(
            Equipment.id,
            Equipment.equipment_no,
            Equipment.model,
            Equipment.status,
            func.count(WellOperation.id),
            func.coalesce(func.sum(WellOperation.run_hours), 0),
        )
        .join(WellOperation, WellOperation.equipment_id == Equipment.id, isouter=True)
        .where(
            (WellOperation.id.is_(None))
            | ((WellOperation.start_date >= start_at) & (WellOperation.start_date <= end_at))
        )
        .group_by(Equipment.id, Equipment.equipment_no, Equipment.model, Equipment.status)
        .order_by(Equipment.equipment_no)
    ).all()

    items = []
    for equipment_id, equipment_no, model, status, count, hours in rows:
        used = Decimal(str(hours or 0))
        rate = (used / total_hours * 100) if total_hours else Decimal("0")
        items.append(
            {
                "equipment_id": equipment_id,
                "equipment_no": equipment_no,
                "model": model,
                "status": status,
                "operation_count": count,
                "run_hours": format(used.quantize(Decimal("0.01")), "f"),
                "utilization_rate": format(rate.quantize(Decimal("0.01")), "f"),
            }
        )

    return {
        "start": start_at.date().isoformat(),
        "end": end_at.date().isoformat(),
        "total_hours": format(total_hours, "f"),
        "formula": "利用率 = 区间内使用时长 ÷ 区间总小时数",
        "items": items,
    }


def fault_statistics(db: Session, start: date | None = None, end: date | None = None) -> dict:
    """故障统计：按故障类型与按月份分布。"""
    start_at, end_at = _range(start, end)
    conditions = (
        FaultRecord.occurred_at.is_not(None),
        FaultRecord.occurred_at >= start_at,
        FaultRecord.occurred_at <= end_at,
    )

    by_type = [
        {"fault_type": fault_type or "未填写", "count": count}
        for fault_type, count in db.execute(
            select(FaultRecord.fault_type, func.count())
            .where(*conditions)
            .group_by(FaultRecord.fault_type)
            .order_by(func.count().desc())
        ).all()
    ]
    by_month = [
        {"month": month, "count": count}
        for month, count in db.execute(
            select(func.date_format(FaultRecord.occurred_at, "%Y-%m"), func.count())
            .where(*conditions)
            .group_by(func.date_format(FaultRecord.occurred_at, "%Y-%m"))
            .order_by(func.date_format(FaultRecord.occurred_at, "%Y-%m"))
        ).all()
    ]
    unresolved = (
        db.scalar(
            select(func.count()).select_from(
                select(FaultRecord.id).where(*conditions, FaultRecord.status != "已解决").subquery()
            )
        )
        or 0
    )

    return {
        "start": start_at.date().isoformat(),
        "end": end_at.date().isoformat(),
        "total": sum(item["count"] for item in by_type),
        "unresolved": unresolved,
        "by_type": by_type,
        "by_month": by_month,
    }


def operation_trend(db: Session, months: int = 6) -> dict:
    """使用趋势：按月统计使用次数与使用时长，并给出按仪器类型的累计时长。"""
    start_at = local_now() - timedelta(days=months * 31)

    by_month = [
        {"month": month, "count": count, "hours": format(Decimal(str(hours or 0)), "f")}
        for month, count, hours in db.execute(
            select(
                func.date_format(WellOperation.start_date, "%Y-%m"),
                func.count(),
                func.coalesce(func.sum(WellOperation.run_hours), 0),
            )
            .where(WellOperation.start_date.is_not(None), WellOperation.start_date >= start_at)
            .group_by(func.date_format(WellOperation.start_date, "%Y-%m"))
            .order_by(func.date_format(WellOperation.start_date, "%Y-%m"))
        ).all()
    ]
    by_instrument = [
        {"instrument_type": instrument or "未填写", "hours": format(Decimal(str(hours or 0)), "f")}
        for instrument, hours in db.execute(
            select(
                WellOperation.instrument_type,
                func.coalesce(func.sum(WellOperation.run_hours), 0),
            )
            .group_by(WellOperation.instrument_type)
            .order_by(func.count().desc())
        ).all()
    ]

    return {"months": months, "by_month": by_month, "by_instrument": by_instrument}
