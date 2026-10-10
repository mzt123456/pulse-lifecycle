"""知识库的请求与响应模型。"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DateTimeStr


class KnowledgeTextCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255, description="标题")
    content: str = Field(min_length=1, description="正文")


class KnowledgeChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    text: str
    char_count: int


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source_type: str
    file_name: str | None
    content_type: str | None
    size_bytes: int | None
    char_count: int
    chunk_count: int
    status: str
    error: str | None
    created_by_name: str | None = None
    created_at: DateTimeStr


class KnowledgeDocumentDetail(KnowledgeDocumentOut):
    """详情带回前几个分块，便于确认解析质量。"""

    chunks: list[KnowledgeChunkOut] = Field(default_factory=list)


class KnowledgeStatsOut(BaseModel):
    documents: int
    chunks: int
    failed: int
    characters: int
