"""维保工单与步骤的请求与响应模型。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DateTimeStr, DecimalStr


class MaintenanceStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int
    name: str
    is_done: bool
    done_by: int | None
    done_by_name: str | None
    done_at: DateTimeStr | None
    remark: str | None


class StepCompleteRequest(BaseModel):
    is_done: bool = Field(default=True, description="true 表示完成，false 表示取消完成")
    remark: str | None = Field(default=None, max_length=255)


class MaintenanceOrderCreate(BaseModel):
    equipment_id: int = Field(description="关联设备 ID，必填")
    level: str = Field(max_length=16, description="维保等级：一级维保、二级维保、三级维保、四级维保")
    start_date: date | None = Field(default=None, description="维保开始日期，留空取今天")
    result: str | None = Field(default=None, max_length=32)
    oil_level: DecimalStr | None = Field(default=None, description="油位（mm）")
    suggestion: str | None = Field(default=None, max_length=500, description="维保建议")


class MaintenanceOrderUpdate(BaseModel):
    level: str | None = Field(default=None, max_length=16, description="改等级会重建步骤清单")
    start_date: date | None = None
    end_date: date | None = None
    result: str | None = Field(default=None, max_length=32)
    oil_level: DecimalStr | None = None
    suggestion: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=16, description="进行中、已完成")
    report_path: str | None = Field(default=None, max_length=255)


class MaintenanceOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    equipment_id: int
    equipment_no: str | None
    level: str
    start_date: date | None
    end_date: date | None
    result: str | None
    oil_level: DecimalStr | None
    suggestion: str | None
    status: str
    report_path: str | None
    created_at: DateTimeStr
    updated_at: DateTimeStr


class MaintenanceOrderDetail(MaintenanceOrderOut):
    """详情与创建返回步骤清单；列表不带，避免每行额外查询。"""

    steps: list[MaintenanceStepOut] = Field(default_factory=list)
