"""字典、附件、审计日志、授权与备份记录。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import ID_TYPE, PkMixin, TimestampMixin


class DictItem(Base, PkMixin, TimestampMixin):
    """基础字典：设备状态、仪器类型、故障类型、维保等级等可选值。"""

    __tablename__ = "dict_items"
    __table_args__ = (
        UniqueConstraint("category", "code", name="uk_dict_items_category_code"),
        Index("idx_dict_items_category", "category"),
    )

    category: Mapped[str] = mapped_column(String(32), nullable=False, comment="字典分类")
    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="取值编码")
    label: Mapped[str] = mapped_column(String(64), nullable=False, comment="显示名称")
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False, comment="排序序号")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, comment="是否启用")


class Attachment(Base, PkMixin):
    """附件元数据；文件本体放在服务器目录，不入库。"""

    __tablename__ = "attachments"
    __table_args__ = (Index("idx_att_object", "object_type", "object_id"),)

    object_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="关联对象类型")
    object_id: Mapped[int] = mapped_column(ID_TYPE, nullable=False, comment="关联对象 ID")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="服务器存储名")
    content_type: Mapped[str | None] = mapped_column(String(64), comment="文件类型")
    size_bytes: Mapped[int | None] = mapped_column(comment="文件大小（字节）")
    storage_path: Mapped[str | None] = mapped_column(String(255), comment="存储相对路径")
    uploaded_by: Mapped[int | None] = mapped_column(ID_TYPE, comment="上传人")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="上传时间")


class AuditLog(Base, PkMixin):
    """审计日志。只提供查询与导出，不提供修改与删除。"""

    __tablename__ = "audit_log"
    __table_args__ = (Index("idx_audit_user_time", "user_id", "created_at"),)

    user_id: Mapped[int | None] = mapped_column(ID_TYPE, comment="操作用户")
    username: Mapped[str | None] = mapped_column(String(64), comment="操作人登录名（冗余留痕）")
    action: Mapped[str] = mapped_column(String(64), nullable=False, comment="动作")
    object_type: Mapped[str | None] = mapped_column(String(32), comment="对象类型")
    object_id: Mapped[int | None] = mapped_column(ID_TYPE, comment="对象 ID")
    detail: Mapped[str | None] = mapped_column(Text, comment="详情（JSON）")
    client_ip: Mapped[str | None] = mapped_column(String(64), comment="来源 IP")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="发生时间")


class License(Base, PkMixin, TimestampMixin):
    """服务器授权：授权编号、有效期与模块范围。"""

    __tablename__ = "licenses"
    __table_args__ = (UniqueConstraint("license_no", name="uk_licenses_license_no"),)

    license_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="授权编号")
    issued_at: Mapped[date | None] = mapped_column(Date, comment="签发日期")
    expires_at: Mapped[date | None] = mapped_column(Date, comment="到期日期")
    modules: Mapped[str | None] = mapped_column(String(255), comment="模块范围")
    renewed_at: Mapped[date | None] = mapped_column(Date, comment="最近续期日期")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")


class BackupRecord(Base, PkMixin):
    """备份记录。"""

    __tablename__ = "backup_records"
    __table_args__ = (Index("idx_backup_created", "created_at"),)

    backup_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="备份类型")
    file_path: Mapped[str | None] = mapped_column(String(255), comment="备份文件路径")
    size_bytes: Mapped[int | None] = mapped_column(comment="文件大小（字节）")
    result: Mapped[str] = mapped_column(String(16), nullable=False, comment="结果")
    message: Mapped[str | None] = mapped_column(String(255), comment="说明")
    created_by: Mapped[int | None] = mapped_column(ID_TYPE, comment="操作人")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="创建时间")
