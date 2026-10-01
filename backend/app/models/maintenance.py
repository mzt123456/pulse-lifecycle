"""维保工单与步骤清单。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.equipment import Equipment
from app.models.mixins import ID_TYPE, AuditMixin, PkMixin
from app.models.user import User


class MaintenanceOrder(Base, PkMixin, AuditMixin):
    """维保工单。工单号沿用“前缀 + 年月日 + 序号”，由唯一索引兜底防重。"""

    __tablename__ = "maintenance_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uk_order_no"),
        Index("idx_mo_equipment_created", "equipment_id", "created_at"),
    )

    order_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="工单号")
    equipment_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("equipment.id"), nullable=False, comment="关联设备"
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, comment="维保等级：一级至四级")
    start_date: Mapped[date | None] = mapped_column(Date, comment="维保开始日期")
    end_date: Mapped[date | None] = mapped_column(Date, comment="维保结束日期")
    result: Mapped[str | None] = mapped_column(String(32), comment="维保结果")
    oil_level: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="油位（mm）")
    suggestion: Mapped[str | None] = mapped_column(String(500), comment="维保建议")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="进行中", comment="状态")
    report_path: Mapped[str | None] = mapped_column(String(255), comment="维保报告文件路径")

    equipment: Mapped[Equipment] = relationship(lazy="joined")
    steps: Mapped[list["MaintenanceStep"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="MaintenanceStep.seq",
    )

    @property
    def equipment_no(self) -> str | None:
        return self.equipment.equipment_no if self.equipment is not None else None


class MaintenanceStep(Base, PkMixin):
    """维保步骤清单，按等级自动生成，逐项记录完成情况。"""

    __tablename__ = "maintenance_steps"
    __table_args__ = (Index("idx_ms_order_seq", "order_id", "seq"),)

    order_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("maintenance_orders.id"), nullable=False, comment="关联工单"
    )
    seq: Mapped[int] = mapped_column(nullable=False, comment="步骤序号")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="步骤内容")
    is_done: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否完成")
    done_by: Mapped[int | None] = mapped_column(ID_TYPE, comment="完成人")
    done_at: Mapped[datetime | None] = mapped_column(DateTime, comment="完成时间")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")

    order: Mapped[MaintenanceOrder] = relationship(back_populates="steps")
    # done_by 故意不加外键（删除用户不应牵连历史记录），因此显式声明连接条件并设为只读
    done_by_user: Mapped[User | None] = relationship(
        primaryjoin=lambda: MaintenanceStep.done_by == User.id,
        foreign_keys=lambda: [MaintenanceStep.done_by],
        viewonly=True,
        lazy="joined",
    )

    @property
    def done_by_name(self) -> str | None:
        """完成人姓名，列表与详情直接展示。"""
        if self.done_by_user is None:
            return None
        return self.done_by_user.real_name or self.done_by_user.username
