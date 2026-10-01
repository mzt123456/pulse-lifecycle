"""模型共用的列定义：主键与时间戳。"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

# 主键与关联字段统一用 BIGINT UNSIGNED，与编写报告 4.3 的类型约定一致
ID_TYPE = BIGINT(unsigned=True)


class PkMixin:
    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="最后修改时间"
    )


class AuditMixin(TimestampMixin):
    """业务表记录创建人与最后修改人。

    这里存用户 ID 而不加外键：删除或停用用户时，历史业务记录不应被牵连。
    """

    created_by: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True, comment="创建人")
    updated_by: Mapped[int | None] = mapped_column(ID_TYPE, nullable=True, comment="最后修改人")
