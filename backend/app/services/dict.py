"""基础字典读取与取值校验：选项统一由字典表维护（编写报告 14.1）。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError, ErrorCode
from app.models.system import DictItem


def options(db: Session, category: str) -> list[str]:
    """取某个分类下的启用取值，按排序序号返回。"""
    return list(
        db.execute(
            select(DictItem.code)
            .where(DictItem.category == category, DictItem.is_active.is_(True))
            .order_by(DictItem.sort_order, DictItem.id)
        ).scalars()
    )


def ensure_value(db: Session, category: str, value: str | None, field: str) -> None:
    """校验取值是否在字典内；字典为空时跳过，避免因未初始化数据卡住业务。"""
    if value is None or value == "":
        return
    allowed = options(db, category)
    if allowed and value not in allowed:
        raise BusinessError(
            ErrorCode.BUSINESS_RULE,
            f"{field}取值不正确：{value}，可选值为 {'、'.join(allowed)}",
            422,
        )
