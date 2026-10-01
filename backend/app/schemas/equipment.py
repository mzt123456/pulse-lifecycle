"""设备台账的请求与响应模型。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DateTimeStr, DecimalStr


class EquipmentCreate(BaseModel):
    equipment_no: str = Field(min_length=1, max_length=64, description="脉冲编号")
    model: str | None = Field(default=None, max_length=64, description="型号")
    status: str = Field(default="待命", max_length=16, description="状态：在用、待命、维保、报废")
    factory_date: date | None = None
    temperature_grade: str | None = Field(default=None, max_length=32)
    pressure_grade: str | None = Field(default=None, max_length=32)
    valve_shell_size: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=128)
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=255)


class EquipmentUpdate(BaseModel):
    """更新时必须带上 version，用于乐观锁校验（编写报告 4.5）。"""

    version: int = Field(ge=1, description="乐观锁版本号，取详情返回的值")
    equipment_no: str | None = Field(default=None, min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=16)
    factory_date: date | None = None
    temperature_grade: str | None = Field(default=None, max_length=32)
    pressure_grade: str | None = Field(default=None, max_length=32)
    valve_shell_size: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=128)
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=255)


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_no: str
    model: str | None
    status: str
    factory_date: date | None
    total_run_hours: DecimalStr
    total_run_count: int
    temperature_grade: str | None
    pressure_grade: str | None
    valve_shell_size: str | None
    company: str | None
    contact_name: str | None
    contact_phone: str | None
    last_maintenance_at: DateTimeStr | None
    remark: str | None
    version: int
    created_at: DateTimeStr
    updated_at: DateTimeStr
