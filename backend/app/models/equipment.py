"""设备台账、子部件与状态流水。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import ID_TYPE, AuditMixin, PkMixin


class Equipment(Base, PkMixin, AuditMixin):
    """设备台账主表。状态取值沿用单机版：在用、待命、维保、报废。"""

    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("equipment_no", name="uk_equipment_no"),)

    equipment_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="脉冲编号")
    model: Mapped[str | None] = mapped_column(String(64), comment="型号")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待命", comment="状态")
    factory_date: Mapped[date | None] = mapped_column(Date, comment="出厂日期")
    total_run_hours: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, comment="累计使用时长（小时）"
    )
    total_run_count: Mapped[int] = mapped_column(default=0, nullable=False, comment="累计使用次数")
    temperature_grade: Mapped[str | None] = mapped_column(String(32), comment="温度等级")
    pressure_grade: Mapped[str | None] = mapped_column(String(32), comment="抗压等级")
    valve_shell_size: Mapped[str | None] = mapped_column(String(32), comment="阀壳尺寸")
    company: Mapped[str | None] = mapped_column(String(128), comment="关联公司")
    contact_name: Mapped[str | None] = mapped_column(String(64), comment="联系人")
    contact_phone: Mapped[str | None] = mapped_column(String(32), comment="联系电话")
    last_maintenance_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近维保时间")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")
    version: Mapped[int] = mapped_column(default=1, nullable=False, comment="乐观锁版本号")


class Component(Base, PkMixin, AuditMixin):
    """子部件与小项，关联设备。"""

    __tablename__ = "components"
    __table_args__ = (Index("idx_components_equipment", "equipment_id"),)

    equipment_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("equipment.id"), nullable=False, comment="关联设备"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="部件名称")
    spec: Mapped[str | None] = mapped_column(String(64), comment="规格型号")
    total_run_hours: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, comment="累计使用时长（小时）"
    )
    status: Mapped[str | None] = mapped_column(String(16), comment="状态")
    installed_at: Mapped[date | None] = mapped_column(Date, comment="安装日期")
    replaced_at: Mapped[date | None] = mapped_column(Date, comment="更换日期")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")


class EquipmentStatusLog(Base, PkMixin):
    """设备状态变更流水。"""

    __tablename__ = "equipment_status_log"
    __table_args__ = (Index("idx_esl_equipment_time", "equipment_id", "changed_at"),)

    equipment_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("equipment.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), comment="变更前状态")
    to_status: Mapped[str] = mapped_column(String(16), nullable=False, comment="变更后状态")
    reason: Mapped[str | None] = mapped_column(String(255), comment="变更原因")
    changed_by: Mapped[int | None] = mapped_column(ID_TYPE, comment="操作人")
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="变更时间")
