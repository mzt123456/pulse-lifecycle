"""技能加载器：渐进式披露的三层结构。

```
第一层（常驻）  技能索引：一行一个「名字 + 一句用途」，永远在提示词里
第二层（命中才加载）  SKILL.md 正文：流程、约束、可用工具、输出格式
第三层（显式引用才加载）references/ 下的参考资料
```

为什么这么做：把所有技能正文和参考资料一股脑塞进系统提示词，每次问答都要为
用不到的内容付 token，而且指令越长模型越容易忽略重点。索引常驻是为了让模型
知道自己有哪些能力，正文按需展开是为了让上下文只装当前这件事。

技能选择先用触发词确定性匹配，命中不到就用基础提示词——不给每次问答增加
一次模型调用。触发词表写在 SKILL.md 的 frontmatter 里，业务变化时改文件即可。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent
FRONTMATTER = re.compile(r"^---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>.*)$", re.DOTALL)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    body: str
    path: Path

    def read_reference(self, filename: str) -> str | None:
        """按需读取参考资料；不存在返回 None，不抛异常。"""
        candidate = (self.path.parent / "references" / filename).resolve()
        if not str(candidate).startswith(str(self.path.parent.resolve())) or not candidate.is_file():
            return None
        return candidate.read_text(encoding="utf-8").strip()

    def references(self) -> list[str]:
        folder = self.path.parent / "references"
        if not folder.is_dir():
            return []
        return sorted(item.name for item in folder.iterdir() if item.is_file())


def _parse(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group("meta").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, match.group("body").strip()


@lru_cache(maxsize=1)
def load_skills() -> tuple[Skill, ...]:
    """扫描技能目录；缺 frontmatter 或没有名字的目录直接跳过。"""
    skills: list[Skill] = []
    for skill_file in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        meta, body = _parse(skill_file.read_text(encoding="utf-8"))
        name = meta.get("name") or skill_file.parent.name
        if not body:
            continue
        skills.append(
            Skill(
                name=name,
                description=meta.get("description", ""),
                triggers=tuple(
                    item.strip() for item in meta.get("triggers", "").split(",") if item.strip()
                ),
                body=body,
                path=skill_file,
            )
        )
    return tuple(skills)


def reload_skills() -> tuple[Skill, ...]:
    """技能文件改动后重新加载（测试与热更新用）。"""
    load_skills.cache_clear()
    return load_skills()


def skill_index(skills: tuple[Skill, ...] | None = None) -> str:
    """第一层：常驻提示词里的技能清单。"""
    items = skills if skills is not None else load_skills()
    return "\n".join(f"- {item.name}：{item.description}" for item in items)


def select_skill(question: str, skills: tuple[Skill, ...] | None = None) -> Skill | None:
    """按触发词命中数量选择技能；一个都没命中就返回 None。"""
    items = skills if skills is not None else load_skills()
    best: Skill | None = None
    best_score = 0
    for skill in items:
        score = sum(1 for trigger in skill.triggers if trigger and trigger in question)
        if score > best_score:
            best, best_score = skill, score
    return best


def render_context(skill: Skill | None, references: list[str] | None = None) -> str:
    """第二、三层：技能正文与按需拉取的参考资料。"""
    if skill is None:
        return ""
    parts = [f"# 当前技能：{skill.name}", skill.body]
    for filename in references or []:
        content = skill.read_reference(filename)
        if content:
            parts.append(f"## 参考：{filename}\n{content}")
    return "\n\n".join(parts)


def full_context_size(skills: tuple[Skill, ...] | None = None) -> int:
    """把所有技能正文与参考资料全量塞进上下文时的字符数，用于对比。"""
    items = skills if skills is not None else load_skills()
    total = 0
    for skill in items:
        total += len(skill.body)
        for filename in skill.references():
            total += len(skill.read_reference(filename) or "")
    return total
