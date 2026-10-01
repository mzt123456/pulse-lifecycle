"""耗材目录、领用与导入的请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConsumableCreate(BaseModel):
    part_no: str = Field(min_length=1, max_length=64, description="部件号")
    description: str = Field(min_length=1, max_length=128, description="中文描述")
    quantity: int = Field(default=0, ge=0, description="库存数量")
    safety_stock: int = Field(default=0, ge=0, description="安全库存")
    unit: str | None = Field(default=None, max_length=16)
    remark: str | None = Field(default=None, max_length=255)


class ConsumableUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=128)
    safety_stock: int | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=16)
    remark: str | None = Field(default=None, max_length=255)


class ConsumableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    part_no: str
    description: str
    quantity: int
    safety_stock: int
    unit: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class ConsumableUsageCreate(BaseModel):
    consumable_id: int = Field(description="耗材 ID")
    quantity: int = Field(gt=0, description="领用数量，必须大于 0")
    order_id: int | None = Field(default=None, description="关联维保工单")
    remark: str | None = Field(default=None, max_length=255)


class ConsumableUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    consumable_id: int
    part_no: str | None
    description: str | None
    order_id: int | None
    quantity: int
    used_by: int | None
    used_by_name: str | None
    used_at: datetime
    remark: str | None


class ImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    failed: int = 0
    errors: list[str] = []
