"""用户、角色、权限、令牌与界面偏好。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import ID_TYPE, PkMixin, TimestampMixin


class User(Base, PkMixin, TimestampMixin):
    """用户账号。密码哈希沿用单机版的 PBKDF2-HMAC-SHA256 格式。"""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uk_users_username"),)

    username: Mapped[str] = mapped_column(String(64), nullable=False, comment="登录名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    real_name: Mapped[str | None] = mapped_column(String(64), comment="姓名")
    phone: Mapped[str | None] = mapped_column(String(32), comment="联系电话")
    department: Mapped[str | None] = mapped_column(String(64), comment="岗位或部门")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, comment="是否启用")
    failed_attempts: Mapped[int] = mapped_column(default=0, nullable=False, comment="连续登录失败次数")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, comment="锁定到期时间")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近登录时间")
    last_login_ip: Mapped[str | None] = mapped_column(String(64), comment="最近登录 IP")


class Role(Base, PkMixin, TimestampMixin):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("name", name="uk_roles_name"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色名称")
    description: Mapped[str | None] = mapped_column(String(255), comment="角色说明")
    is_builtin: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否内置角色")


class Permission(Base, PkMixin, TimestampMixin):
    """权限点按“模块 + 操作”定义，例如 equipment.view。"""

    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code", name="uk_permissions_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="权限点编码")
    module: Mapped[str] = mapped_column(String(32), nullable=False, comment="所属模块")
    action: Mapped[str] = mapped_column(String(32), nullable=False, comment="操作")
    description: Mapped[str | None] = mapped_column(String(255), comment="说明")


class RolePermission(Base, PkMixin, TimestampMixin):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uk_role_permissions"),)

    role_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("permissions.id"), nullable=False)


class UserRole(Base, PkMixin, TimestampMixin):
    """用户与角色关联，支持一人多角色。"""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uk_user_roles"),)

    user_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("roles.id"), nullable=False)


class RefreshToken(Base, PkMixin, TimestampMixin):
    """刷新令牌，可撤销，用于强制下线。"""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_id", name="uk_refresh_tokens_token_id"),
        Index("idx_rt_user_expires", "user_id", "expires_at"),
    )

    user_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id"), nullable=False)
    token_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="令牌标识（jti）")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="到期时间")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, comment="撤销时间")
    client_ip: Mapped[str | None] = mapped_column(String(64), comment="签发时来源 IP")
    user_agent: Mapped[str | None] = mapped_column(String(255), comment="签发时客户端标识")


class UserPreference(Base, PkMixin, TimestampMixin):
    """界面偏好，随账号漫游：表格列设置、每页条数、导航折叠状态。"""

    __tablename__ = "user_preferences"
    __table_args__ = (UniqueConstraint("user_id", name="uk_user_preferences_user_id"),)

    user_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("users.id"), nullable=False)
    page_size: Mapped[int] = mapped_column(default=20, nullable=False, comment="每页条数")
    nav_collapsed: Mapped[bool] = mapped_column(default=False, nullable=False, comment="导航是否折叠")
    table_columns: Mapped[str | None] = mapped_column(Text, comment="各列表的列显示与顺序（JSON）")
