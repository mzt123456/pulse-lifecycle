"""审计日志与附件的请求与响应模型。"""

from pydantic import BaseModel, ConfigDict

from app.schemas.common import DateTimeStr


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    username: str | None
    action: str
    object_type: str | None
    object_id: int | None
    detail: str | None
    client_ip: str | None
    created_at: DateTimeStr


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    object_type: str
    object_id: int
    file_name: str
    content_type: str | None
    size_bytes: int | None
    uploaded_by: int | None
    uploaded_at: DateTimeStr
