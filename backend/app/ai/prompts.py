"""诊断提示词：只依据检索到的案例作答，并强制给出引用。

提示词里用 C1、C2 这种短编号指代案例，模型更容易稳定引用；业务层再把
编号映射回语料文档 ID，避免让模型直接复述 `synthetic:电气故障:003` 这类
带冒号的标识（实测这类字符串容易被改写或截断）。
"""

from collections.abc import Sequence

from app.ai.retriever import SearchHit

MAX_CASES_IN_PROMPT = 8

SYSTEM_PROMPT = """你是井下剪切阀脉冲器的故障诊断助手，服务对象是现场维保人员。

必须遵守的规则：
1. 只能依据用户消息里给出的「相似案例」作答，不要引入案例之外的经验或常识；
2. 每条可能原因和建议处置都必须给出支撑它的案例编号（case_ids），留空表示没有依据，那就不要写；
3. 案例不足以支撑判断时，confidence 填「低」，并在 note 里说明还需要补充哪些信息；
4. 只输出 JSON 对象，不要输出 Markdown 代码块、解释文字或前后缀。

输出格式：
{"causes":[{"text":"可能原因","case_ids":["C1"]}],
 "actions":[{"text":"建议处置","case_ids":["C1"]}],
 "confidence":"高|中|低",
 "note":"补充说明，没有就填空字符串"}
"""


def build_cases_block(hits: Sequence[SearchHit]) -> tuple[str, dict[str, str]]:
    """渲染案例清单，并返回「案例编号 -> 语料文档 ID」的映射。"""
    lines: list[str] = []
    case_map: dict[str, str] = {}

    for index, hit in enumerate(hits[:MAX_CASES_IN_PROMPT], start=1):
        alias = f"C{index}"
        case_map[alias] = hit.document.doc_id
        lines.append(f"[{alias}] 来源：{hit.document.source_label}")
        lines.append(hit.document.text)
        lines.append("")

    return "\n".join(lines).strip(), case_map


def build_diagnosis_prompt(
    *,
    description: str,
    cases_block: str,
    fault_type: str | None = None,
    instrument_type: str | None = None,
    equipment_no: str | None = None,
) -> str:
    """拼出用户消息：先给查询上下文，再给案例清单。"""
    context = [f"【现象描述】{description}"]
    if fault_type:
        context.append(f"【故障类型】{fault_type}")
    if instrument_type:
        context.append(f"【仪器类型】{instrument_type}")
    if equipment_no:
        context.append(f"【设备编号】{equipment_no}")

    return (
        "请根据下面的相似案例，给出可能原因、建议处置与置信度。\n\n"
        + "\n".join(context)
        + "\n\n【相似案例】\n"
        + cases_block
    )
