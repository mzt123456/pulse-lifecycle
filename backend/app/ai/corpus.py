"""智能助手的语料构建。

语料源可插拔，目前两类：

- 真实故障记录（fault_records）：只收「现象 + 原因或解决方案」齐全的记录，
  是甲方历史数据迁移到位后的正式语料；
- 仿真案例（synthetic）：按业务字典构造，用于历史数据到位前跑通链路与评测，
  来源单独标记，不会与真实记录混淆。

真实数据接入后只需替换数据源，检索与生成链路保持不变。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.document import (
    SOURCE_FAULT_RECORD,
    SOURCE_KNOWLEDGE,
    SOURCE_LABELS,
    CaseDocument,
    render_fault_text,
)
from app.ai.synthetic_cases import build_synthetic_case_documents
from app.models.fault import FaultRecord
from app.models.knowledge import STATUS_READY, KnowledgeChunk, KnowledgeDocument


def build_fault_case_documents(db: Session, *, limit: int | None = None) -> list[CaseDocument]:
    """从故障记录构造语料。

    只保留有现象描述、且原因或解决方案至少有一项的记录——现象是检索入口，
    原因与处置是回答内容，缺任何一头这条记录都不具备复用价值。
    """
    stmt = select(FaultRecord).order_by(FaultRecord.id)
    if limit is not None:
        stmt = stmt.limit(limit)

    documents: list[CaseDocument] = []
    for record in db.execute(stmt).unique().scalars():
        if not record.description or not (record.cause or record.solution):
            continue

        equipment = record.equipment
        model = equipment.model if equipment else None
        documents.append(
            CaseDocument(
                source=SOURCE_FAULT_RECORD,
                doc_id=f"fault:{record.id}",
                title=f"{record.fault_type or '未分类'}｜{record.description}",
                text=render_fault_text(
                    description=record.description,
                    cause=record.cause,
                    solution=record.solution,
                    fault_type=record.fault_type,
                    model=model,
                ),
                payload={
                    "record_id": record.id,
                    "equipment_id": record.equipment_id,
                    "equipment_no": equipment.equipment_no if equipment else None,
                    "model": model,
                    # 仪器类型在仿真案例里是字典取值；真实记录用设备型号对齐，
                    # 这样按仪器类型过滤时两类语料落在同一个字段上。
                    "instrument_type": model,
                    "fault_type": record.fault_type,
                    "status": record.status,
                    # 降级路径要直接回显原因与处置，避免为了这两列再查一次库
                    "description": record.description,
                    "cause": record.cause,
                    "solution": record.solution,
                },
            )
        )
    return documents


def build_knowledge_documents(db: Session, *, limit: int | None = None) -> list[CaseDocument]:
    """从知识库分块构造语料。

    检索的最小单位是**分块**而不是整篇文档：一篇规范动辄上千字，整篇进索引会让
    BM25 的长度归一化失真、向量也会被稀释。命中后靠 payload 里的 document_id 回指原文。
    """
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .where(
            KnowledgeDocument.is_deleted.is_(False),
            KnowledgeDocument.status == STATUS_READY,
        )
        .order_by(KnowledgeChunk.document_id, KnowledgeChunk.seq)
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    documents: list[CaseDocument] = []
    for chunk, document in db.execute(stmt).all():
        documents.append(
            CaseDocument(
                source=SOURCE_KNOWLEDGE,
                doc_id=f"knowledge:{document.id}:{chunk.seq}",
                title=f"{document.title}｜第 {chunk.seq} 段",
                text=chunk.text,
                payload={
                    "document_id": document.id,
                    "chunk_seq": chunk.seq,
                    "title": document.title,
                    "file_name": document.file_name,
                    "source_type": document.source_type,
                },
            )
        )
    return documents


def build_corpus(db: Session, *, include_synthetic: bool = True) -> list[CaseDocument]:
    """汇总语料：故障记录与知识库文档在前，仿真案例在后。"""
    documents = build_fault_case_documents(db)
    documents.extend(build_knowledge_documents(db))
    if include_synthetic:
        documents.extend(build_synthetic_case_documents())
    return documents


def corpus_stats(db: Session, *, include_synthetic: bool = True) -> dict:
    """语料规模与来源构成，供演示与排查使用（真实数据接入后可对比两类的占比）。"""
    documents = build_corpus(db, include_synthetic=include_synthetic)
    counts: dict[str, int] = {}
    for document in documents:
        counts[document.source] = counts.get(document.source, 0) + 1

    return {
        "total": len(documents),
        "include_synthetic": include_synthetic,
        "by_source": [
            {
                "source": source,
                "source_label": SOURCE_LABELS.get(source, source),
                "count": count,
            }
            for source, count in sorted(counts.items())
        ],
    }
