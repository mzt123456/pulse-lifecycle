"""故障记录。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.equipment import Equipment
from app.models.mixins import ID_TYPE, AuditMixin, PkMixin


class FaultRecord(Base, PkMixin, AuditMixin):
    __tablename__ = "fault_records"
    __table_args__ = (Index("idx_fr_equipment_time", "equipment_id", "occurred_at"),)

    equipment_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("equipment.id"), nullable=False, comment="关联设备"
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, comment="故障发生时间")
    position: Mapped[str | None] = mapped_column(String(64), comment="故障位置")
    fault_type: Mapped[str | None] = mapped_column(String(64), comment="故障类型")
    description: Mapped[str | None] = mapped_column(String(500), comment="现象描述")
    cause: Mapped[str | None] = mapped_column(String(500), comment="原因分析")
    solution: Mapped[str | None] = mapped_column(String(500), comment="解决方案")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待处理", comment="处理状态")

    equipment: Mapped[Equipment] = relationship(lazy="joined")

    @property
    def equipment_no(self) -> str | None:
        return self.equipment.equipment_no if self.equipment is not None else None
