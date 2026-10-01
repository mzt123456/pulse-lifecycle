"""故障记录的请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DateTimeStr


class FaultRecordCreate(BaseModel):
    equipment_id: int = Field(description="关联设备 ID，必填")
    occurred_at: datetime | None = Field(default=None, description="故障发生时间")
    position: str | None = Field(default=None, max_length=64, description="故障位置")
    fault_type: str | None = Field(default=None, max_length=64, description="故障类型，取值来自字典")
    description: str | None = Field(default=None, max_length=500, description="现象描述")
    cause: str | None = Field(default=None, max_length=500, description="原因分析")
    solution: str | None = Field(default=None, max_length=500, description="解决方案")
    status: str = Field(default="待处理", max_length=16, description="处理状态，取值来自字典")


class FaultRecordUpdate(BaseModel):
    occurred_at: datetime | None = None
    position: str | None = Field(default=None, max_length=64)
    fault_type: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    cause: str | None = Field(default=None, max_length=500)
    solution: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=16)


class FaultRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    equipment_no: str | None
    occurred_at: DateTimeStr | None
    position: str | None
    fault_type: str | None
    description: str | None
    cause: str | None
    solution: str | None
    status: str
    created_at: DateTimeStr
    updated_at: DateTimeStr
