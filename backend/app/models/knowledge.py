"""知识库：手工维护的文档与分块。

两条语料来源并存：故障记录（结构化案例，现象/原因/处置）与知识库文档（自由文本）。
两者最终都产出 `CaseDocument`，所以检索、重排、引用校验不需要区分。

文档删除用软删除：内容可以恢复，审计也能查到是谁删的；语料侧只取未删除且解析成功的文档。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import ID_TYPE, AuditMixin, PkMixin, TimestampMixin

# 解析状态：ready 表示已入库可检索；failed 时 error 里写明原因（页面直接展示）
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# 来源：text 是页面粘贴，file 是上传文件
SOURCE_TEXT = "text"
SOURCE_FILE = "file"


class KnowledgeDocument(Base, PkMixin, AuditMixin):
    """一篇知识库文档。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("idx_kdoc_status", "status", "is_deleted"),)

    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="来源：text/file")
    file_name: Mapped[str | None] = mapped_column(String(255), comment="原始文件名")
    stored_name: Mapped[str | None] = mapped_column(String(255), comment="服务器存储名")
    # docx 的 MIME 是 application/vnd.openxmlformats-officedocument.wordprocessingml.document（71 字符）
    content_type: Mapped[str | None] = mapped_column(String(128), comment="文件类型")
    size_bytes: Mapped[int | None] = mapped_column(comment="文件大小（字节）")
    char_count: Mapped[int] = mapped_column(default=0, nullable=False, comment="正文总字数")
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False, comment="分块数")
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="解析状态")
    error: Mapped[str | None] = mapped_column(String(255), comment="解析失败原因")
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否已删除")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, comment="删除时间")

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base, PkMixin, TimestampMixin):
    """文档分块；检索的最小单位。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("idx_kchunk_doc", "document_id", "seq"),)

    document_id: Mapped[int] = mapped_column(
        ID_TYPE, ForeignKey("knowledge_documents.id"), nullable=False, comment="所属文档"
    )
    seq: Mapped[int] = mapped_column(nullable=False, comment="块序号，从 1 开始")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="块正文")
    char_count: Mapped[int] = mapped_column(default=0, nullable=False, comment="块字数")

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
