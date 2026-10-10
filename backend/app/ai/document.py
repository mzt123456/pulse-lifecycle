"""智能助手的语料文档模型与渲染。

检索层只认 CaseDocument，不关心数据从哪来；source 字段用于区分真实记录与
仿真案例，保证两者不会在展示与评测里被混为一谈。
"""

from dataclasses import dataclass, field
from typing import Any

SOURCE_FAULT_RECORD = "fault_record"
SOURCE_SYNTHETIC = "synthetic"
SOURCE_KNOWLEDGE = "knowledge"

SOURCE_LABELS: dict[str, str] = {
    SOURCE_FAULT_RECORD: "历史故障记录",
    SOURCE_SYNTHETIC: "仿真案例",
    SOURCE_KNOWLEDGE: "知识库文档",
}


@dataclass(frozen=True)
class CaseDocument:
    """一条可检索的语料。

    text 是检索与生成用的正文，payload 保留结构化字段，供检索预过滤与结果回显。
    """

    source: str
    doc_id: str
    title: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)


def render_fault_text(
    *,
    description: str | None,
    cause: str | None = None,
    solution: str | None = None,
    fault_type: str | None = None,
    instrument_type: str | None = None,
    model: str | None = None,
) -> str:
    """把故障案例的字段拼成一段可检索文本，空字段自动省略。"""
    parts: list[str] = []

    meta = "  ".join(
        f"【{label}】{value}"
        for label, value in (
            ("仪器类型", instrument_type),
            ("设备型号", model),
            ("故障类型", fault_type),
        )
        if value
    )
    if meta:
        parts.append(meta)

    for label, value in (("现象", description), ("原因", cause), ("处置", solution)):
        if value:
            parts.append(f"【{label}】{value}")

    return "\n".join(parts)
