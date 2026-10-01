"""耗材目录与领用明细。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import ID_TYPE, AuditMixin, PkMixin, TimestampMixin


class Consumable(Base, PkMixin, AuditMixin):
    """耗材目录与库存。领用扣减需在同一事务内加行级锁。"""

    __tablename__ = "consumables"
    __table_args__ = (UniqueConstraint("part_no", name="uk_part_no"),)

    part_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="部件号")
    description: Mapped[str] = mapped_column(String(128), nullable=False, comment="中文描述")
    quantity: Mapped[int] = mapped_column(default=0, nullable=False, comment="库存数量")
    safety_stock: Mapped[int] = mapped_column(default=0, nullable=False, comment="安全库存")
    unit: Mapped[str | None] = mapped_column(String(16), comment="单位")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")


class ConsumableUsage(Base, PkMixin, TimestampMixin):
    """耗材领用明细。"""

    __tablename__ = "consumable_usages"
    __table_args__ = (Index("idx_cu_consumable_time", "consumable_id", "used_at"),)

    consumable_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("consumables.id"), nullable=False, comment="关联耗材"
    )
    order_id: Mapped[int | None] = mapped_column(
        ID_TYPE, ForeignKey("maintenance_orders.id"), comment="关联维保工单"
    )
    quantity: Mapped[int] = mapped_column(nullable=False, comment="领用数量")
    used_by: Mapped[int | None] = mapped_column(ID_TYPE, comment="领用人")
    used_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="领用时间")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")
