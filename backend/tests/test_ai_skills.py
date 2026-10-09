"""技能机制用例：索引常驻、正文按需、参考资料显式加载。"""

import pytest

from app.ai.skills.loader import (
    full_context_size,
    load_skills,
    reload_skills,
    render_context,
    select_skill,
    skill_index,
)


def test_skills_are_discovered_with_metadata() -> None:
    skills = load_skills()
    names = {skill.name for skill in skills}

    assert {"fault_diagnosis", "asset_query"} <= names
    for skill in skills:
        assert skill.description, f"{skill.name} 缺少一句话用途"
        assert skill.triggers, f"{skill.name} 缺少触发词"
        assert skill.body


def test_index_is_only_names_and_descriptions() -> None:
    """常驻提示词里不能出现技能正文，否则就失去按需加载的意义。"""
    index = skill_index()
    skills = load_skills()

    assert len(index.splitlines()) == len(skills)
    for skill in skills:
        assert skill.name in index
        assert skill.body not in index


def test_progressive_disclosure_keeps_index_much_smaller_than_full_context() -> None:
    assert len(skill_index()) < full_context_size() / 3


def test_select_skill_by_trigger_words() -> None:
    skills = load_skills()

    fault = select_skill("下井之后收不到脉冲信号，可能是什么原因", skills)
    asset = select_skill("耗材库存还剩多少", skills)

    assert fault is not None and fault.name == "fault_diagnosis"
    assert asset is not None and asset.name == "asset_query"


def test_select_skill_returns_none_for_unrelated_question() -> None:
    assert select_skill("食堂午餐菜单今天有什么", load_skills()) is None


def test_render_context_includes_body_and_requested_reference() -> None:
    skill = next(item for item in load_skills() if item.name == "fault_diagnosis")
    references = skill.references()

    assert references, "故障诊断技能应当带参考资料"
    context = render_context(skill, references[:1])

    assert skill.body in context
    assert references[0] in context
    assert len(context) > len(skill.body)


def test_reference_loading_rejects_path_traversal() -> None:
    skill = load_skills()[0]

    assert skill.read_reference("../../../../etc/passwd") is None
    assert skill.read_reference("不存在的文件.md") is None


def test_reload_skills_refreshes_cache() -> None:
    pytest.importorskip("app.ai.skills.loader")
    assert reload_skills() == load_skills()
