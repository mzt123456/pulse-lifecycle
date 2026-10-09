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

from app.ai.document import SOURCE_FAULT_RECORD, SOURCE_LABELS, CaseDocument, render_fault_text
from app.ai.synthetic_cases import build_synthetic_case_documents
from app.models.fault import FaultRecord


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


def build_corpus(db: Session, *, include_synthetic: bool = True) -> list[CaseDocument]:
    """汇总语料：真实故障记录在前，仿真案例在后。"""
    documents = build_fault_case_documents(db)
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
