"""通用请求与响应模型。"""

from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, Field, PlainSerializer

T = TypeVar("T")

# 定点数以字符串传输，避免浮点误差（编写报告 5.1）。
# when_used="json"：只在出参序列化时转字符串，model_dump() 仍保持 Decimal 供入库使用。
DecimalStr = Annotated[
    Decimal,
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
]


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数，上限 100")
