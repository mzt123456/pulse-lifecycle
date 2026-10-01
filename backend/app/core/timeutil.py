"""时间工具：数据库用本地时间（Asia/Shanghai），令牌用 UTC。"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

LOCAL_ZONE = ZoneInfo("Asia/Shanghai")


def local_now() -> datetime:
    """返回不带时区信息的本地时间，用于 DATETIME 字段（编写报告 4.1）。"""
    return datetime.now(LOCAL_ZONE).replace(tzinfo=None)


def utc_now() -> datetime:
    """返回带时区的 UTC 时间，用于令牌的签发与过期判断。"""
    return datetime.now(UTC)


def to_local_naive(value: datetime) -> datetime:
    """把带时区的时间换算成本地时间并去掉时区信息，便于写入 DATETIME 字段。"""
    if value.tzinfo is None:
        return value
    return value.astimezone(LOCAL_ZONE).replace(tzinfo=None)
