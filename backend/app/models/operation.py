"""使用记录（下井作业）与测量记录。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import ID_TYPE, AuditMixin, PkMixin


class WellOperation(Base, PkMixin, AuditMixin):
    """使用记录。字段沿用单机版，顺序按编写报告 4.3 的示例。"""

    __tablename__ = "well_operations"
    __table_args__ = (
        Index("idx_wo_equipment_start", "equipment_id", "start_date"),
        Index("idx_wo_well_no", "well_no"),
    )

    equipment_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("equipment.id"), nullable=False, comment="关联设备"
    )
    well_no: Mapped[str | None] = mapped_column(String(64), comment="井号")
    well_depth: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), comment="井深")
    bit_size: Mapped[str | None] = mapped_column(String(32), comment="井眼尺寸")
    mud_type: Mapped[str | None] = mapped_column(String(32), comment="泥浆类型")
    mud_density: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), comment="泥浆密度")
    flow_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), comment="排量")
    start_date: Mapped[datetime | None] = mapped_column(DateTime, comment="入井时间")
    end_date: Mapped[datetime | None] = mapped_column(DateTime, comment="出井时间")
    run_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), comment="使用时间（小时）")
    run_in_depth: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), comment="入井井深")
    run_out_depth: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), comment="出井井深")
    footage: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), comment="进尺")
    temperature: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="井下温度")
    instrument_type: Mapped[str | None] = mapped_column(String(32), comment="仪器类型")
    instrument_config: Mapped[str | None] = mapped_column(String(128), comment="仪器配置")
    operator_name: Mapped[str | None] = mapped_column(String(64), comment="作业人员")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")


class MeasurementRecord(Base, PkMixin, AuditMixin):
    """测量记录，关联维保工单或使用记录。"""

    __tablename__ = "measurement_records"
    __table_args__ = (Index("idx_mr_order", "order_id"), Index("idx_mr_operation", "operation_id"))

    order_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("maintenance_orders.id"), comment="关联维保工单"
    )
    operation_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("well_operations.id"), comment="关联使用记录"
    )
    measure_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="测量类型")
    value: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), comment="测量值")
    unit: Mapped[str | None] = mapped_column(String(16), comment="单位")
    measured_at: Mapped[datetime | None] = mapped_column(DateTime, comment="测量时间")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")
