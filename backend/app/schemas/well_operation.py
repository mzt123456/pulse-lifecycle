"""使用记录（下井作业）的请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DateTimeStr, DecimalStr


class WellOperationFields(BaseModel):
    well_no: str | None = Field(default=None, max_length=64, description="井号")
    well_depth: DecimalStr | None = Field(default=None, description="井深")
    bit_size: str | None = Field(default=None, max_length=32, description="井眼尺寸")
    mud_type: str | None = Field(default=None, max_length=32, description="泥浆类型")
    mud_density: DecimalStr | None = Field(default=None, description="泥浆密度")
    flow_rate: DecimalStr | None = Field(default=None, description="排量")
    start_date: datetime | None = Field(default=None, description="入井时间")
    end_date: datetime | None = Field(default=None, description="出井时间")
    run_hours: DecimalStr | None = Field(default=None, description="使用时间，留空按起止时间计算")
    run_in_depth: DecimalStr | None = Field(default=None, description="入井井深")
    run_out_depth: DecimalStr | None = Field(default=None, description="出井井深")
    footage: DecimalStr | None = Field(default=None, description="进尺，留空按出入井井深计算")
    temperature: DecimalStr | None = Field(default=None, description="井下温度")
    instrument_type: str | None = Field(default=None, max_length=32, description="仪器类型")
    instrument_config: str | None = Field(default=None, max_length=128, description="仪器配置")
    operator_name: str | None = Field(default=None, max_length=64, description="作业人员")
    remark: str | None = Field(default=None, max_length=255)


class WellOperationCreate(WellOperationFields):
    equipment_id: int = Field(description="关联设备 ID，必填")


class WellOperationUpdate(WellOperationFields):
    """归属设备不可变更；如需换设备，删除后重新登记。"""


class WellOperationOut(WellOperationFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_id: int
    equipment_no: str | None = Field(default=None, description="脉冲编号，便于列表展示")
    start_date: DateTimeStr | None = Field(default=None, description="入井时间")
    end_date: DateTimeStr | None = Field(default=None, description="出井时间")
    created_at: DateTimeStr
    updated_at: DateTimeStr
