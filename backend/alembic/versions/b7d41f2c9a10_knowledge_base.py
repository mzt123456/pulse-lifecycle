"""knowledge base documents and chunks

Revision ID: b7d41f2c9a10
Revises: 1a9fc138996b
Create Date: 2026-10-11 10:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "b7d41f2c9a10"
down_revision: str | None = "1a9fc138996b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("title", sa.String(length=255), nullable=False, comment="标题"),
        sa.Column("source_type", sa.String(length=16), nullable=False, comment="来源：text/file"),
        sa.Column("file_name", sa.String(length=255), nullable=True, comment="原始文件名"),
        sa.Column("stored_name", sa.String(length=255), nullable=True, comment="服务器存储名"),
        sa.Column("content_type", sa.String(length=128), nullable=True, comment="文件类型"),
        sa.Column("size_bytes", sa.Integer(), nullable=True, comment="文件大小（字节）"),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0", comment="正文总字数"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0", comment="分块数"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="解析状态"),
        sa.Column("error", sa.String(length=255), nullable=True, comment="解析失败原因"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0", comment="是否已删除"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=True, comment="创建人"),
        sa.Column("updated_by", mysql.BIGINT(unsigned=True), nullable=True, comment="最后修改人"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="最后修改时间"
        ),
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
    )
    op.create_index(
        "idx_kdoc_status", "knowledge_documents", ["status", "is_deleted"], unique=False
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("document_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属文档"),
        sa.Column("seq", sa.Integer(), nullable=False, comment="块序号，从 1 开始"),
        sa.Column("text", sa.Text(), nullable=False, comment="块正文"),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0", comment="块字数"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="最后修改时间"
        ),
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_chunks_document_id_knowledge_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
    )
    op.create_index("idx_kchunk_doc", "knowledge_chunks", ["document_id", "seq"], unique=False)


def downgrade() -> None:
    # 回退直接删表：MySQL 允许外键复用同名列上的索引，先删索引会报
    # "Cannot drop index ... needed in a foreign key constraint"，索引随表一并删除。
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
