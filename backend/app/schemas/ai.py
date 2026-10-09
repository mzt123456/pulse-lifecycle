"""智能运维助手的请求与响应模型。"""

from typing import Any

from pydantic import BaseModel, Field


class DiagnosisRequest(BaseModel):
    description: str = Field(
        min_length=4,
        max_length=500,
        description="故障现象，用现场的话描述即可",
    )
    equipment_id: int | None = Field(default=None, description="关联设备，可选；用于补充型号与编号")
    fault_type: str | None = Field(default=None, max_length=64, description="故障类型，取值来自字典")
    instrument_type: str | None = Field(
        default=None, max_length=64, description="仪器类型，取值来自字典"
    )
    top_k: int = Field(default=5, ge=1, le=20, description="检索相似案例的条数")


class DiagnosisMatch(BaseModel):
    """一条被检索到的相似案例。"""

    alias: str = Field(description="提示词里的案例编号，如 C1")
    doc_id: str
    source: str
    source_label: str
    title: str
    score: float
    matched_terms: list[str]
    record_id: int | None = None
    equipment_no: str | None = None
    fault_type: str | None = None
    cause: str | None = None
    solution: str | None = None


class DiagnosisItem(BaseModel):
    """一条可能原因或建议处置，带支撑它的案例 ID。"""

    text: str
    case_ids: list[str]


class DiagnosisOut(BaseModel):
    found: bool = Field(description="是否检索到相似案例")
    degraded: bool = Field(description="是否降级（未经过大模型归纳）")
    reason: str | None = Field(default=None, description="未找到或降级的原因")
    causes: list[DiagnosisItem]
    actions: list[DiagnosisItem]
    confidence: str | None = None
    note: str | None = None
    citations: list[str] = Field(default_factory=list, description="本次结论引用的语料文档 ID")
    matches: list[DiagnosisMatch]
    model: str | None = None
    elapsed_ms: int
    filter_relaxed: bool = Field(description="是否因条件过窄而放宽了结构化过滤")


class CorpusSourceStat(BaseModel):
    source: str
    source_label: str
    count: int


class CorpusStatsOut(BaseModel):
    total: int
    include_synthetic: bool
    by_source: list[CorpusSourceStat]


class AskRequest(BaseModel):
    question: str = Field(min_length=4, max_length=300, description="用自然语言问一个业务问题")
    max_steps: int = Field(default=5, ge=1, le=8, description="工具调用步数上限")


class AskStepOut(BaseModel):
    """一次工具调用：调了什么、参数、结果与耗时，便于前端展示与排查。"""

    step: int
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    elapsed_ms: int


class AskContextOut(BaseModel):
    """上下文规模，用来体现技能按需加载省了多少。"""

    system_prompt: int
    skill_index: int
    all_skills_full: int


class AskOut(BaseModel):
    answer: str | None = None
    skill: str | None = Field(default=None, description="本次命中的技能名，未命中为空")
    steps: list[AskStepOut]
    used_tools: list[str]
    degraded: bool
    reason: str | None = None
    model: str | None = None
    elapsed_ms: int
    context_chars: AskContextOut
