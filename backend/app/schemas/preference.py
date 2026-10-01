"""用户界面偏好的请求与响应模型。"""

from pydantic import BaseModel, Field


class PreferencesOut(BaseModel):
    page_size: int
    nav_collapsed: bool
    table_columns: dict[str, list[str]] = Field(
        default_factory=dict, description="各列表可见列及其顺序，键为表格标识"
    )


class PreferencesUpdate(BaseModel):
    page_size: int | None = Field(default=None, ge=5, le=200)
    nav_collapsed: bool | None = None
    table_columns: dict[str, list[str]] | None = None
