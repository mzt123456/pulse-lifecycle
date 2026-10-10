"""工具执行层：权限校验、执行、计时与审计。

工具**怎么定义**在 `tool_defs.py`（用 LangChain 的 @tool 写，参数 schema 自动生成）；
这个文件只管**怎么执行**，三条约定是这个项目原有的规矩在 AI 侧的延续：

1. **不另写查询。** 工具调用现有 service 函数，权限与业务口径跟着现有实现走，
   AI 模块里不出现一句 SQL；
2. **权限先于调用。** 用户没有某工具对应的权限点，这个工具根本不暴露给模型
   （见 `tools_for`），即使模型坚持要调，`run_tool` 也会再挡一次；
3. **每次调用都留痕。** 审计挂在当前事务上，与业务动作同生共死。

这三件事都是"业务插桩"，所以留在自己手里，没有交给框架的 ToolNode：
框架负责把工具执行完，我们负责在执行前后插入权限与审计。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session
from langchain_core.tools import StructuredTool
from pydantic import create_model

from app.core.audit import record_audit
from app.core.errors import BusinessError
from app.models.user import User
from app.services import equipment as equipment_service

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


@dataclass(frozen=True)
class ToolContext:
    """一次工具调用需要的东西：会话、调用者、调用者权限、来源 IP。

    它通过 `InjectedToolArg` 注入 @tool 函数，不会出现在模型可见的参数表里。
    """

    db: Session
    user: User
    permissions: frozenset[str]
    client_ip: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    """工具的注册单元：模型看到的是前四项，执行时用 handler。"""

    name: str
    description: str
    permission: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


# ----------------------------------------------------------------- 参数收敛
# 参数类型已由 Pydantic 校验过，这里处理的是"业务口径"：长度上限、条数上限、模糊布尔值


def _text(value: Any, *, max_length: int = 64) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_length] or None


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "是"}
    return bool(value)


def _limit(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(number, MAX_LIMIT))


def resolve_equipment_id(ctx: ToolContext, equipment_no: str | None) -> int | None:
    """按脉冲编号精确匹配设备；匹配不到返回 None，由调用方如实告知模型。"""
    if not equipment_no:
        return None
    items, _ = equipment_service.list_equipment(ctx.db, keyword=equipment_no, page_size=5)
    for item in items:
        if item.equipment_no == equipment_no:
            return item.id
    return items[0].id if len(items) == 1 else None


# ----------------------------------------------------------------- 注册与执行


def default_registry() -> dict[str, ToolSpec]:
    """默认工具注册表由 `tool_defs` 提供。

    放在函数里延迟导入：工具定义要引用本模块的 ToolSpec 与参数收敛函数，
    模块级互相导入会成环。
    """
    from app.ai.tool_defs import TOOLS_BY_NAME

    return TOOLS_BY_NAME


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _python_type(schema: dict[str, Any]) -> Any:
    """把 JSON Schema 的类型映射成 Python 类型（含 Optional 的 anyOf 写法）。"""
    if isinstance(schema.get("type"), str) and schema["type"] in _TYPE_MAP:
        return _TYPE_MAP[schema["type"]]
    for option in schema.get("anyOf", []) or []:
        if isinstance(option, dict) and option.get("type") in _TYPE_MAP:
            return _TYPE_MAP[option["type"]]
    return Any


def _args_schema(spec: ToolSpec) -> Any:
    """按 ToolSpec 的参数表建一个 Pydantic 模型，供 LangChain 工具使用。"""
    properties = spec.parameters.get("properties", {}) or {}
    required = set(spec.parameters.get("required", []) or [])

    fields: dict[str, Any] = {}
    for name, schema in properties.items():
        annotation = _python_type(schema) if isinstance(schema, dict) else Any
        if name in required:
            fields[name] = (annotation, ...)
        elif annotation is Any:
            fields[name] = (Any, schema.get("default") if isinstance(schema, dict) else None)
        else:
            fields[name] = (
                annotation | None,
                schema.get("default") if isinstance(schema, dict) else None,
            )
    return create_model(f"{spec.name}_args", **fields)


def as_langchain_tool(spec: ToolSpec, ctx: ToolContext | None = None) -> StructuredTool:
    """把 ToolSpec 转成 LangChain 工具对象（供 bind_tools 使用）。

    只是同一个工具的另一种表示：参数 schema 转成 Pydantic 模型，
    **执行仍然走 `run_tool`**（权限校验与审计在里面）。带上 ctx 的工具也能被
    框架的 ToolNode 直接执行；不带 ctx 时明确报错，避免绕过审计。
    """
    args_schema = _args_schema(spec)

    def _run(**kwargs: Any) -> str:
        if ctx is None:
            raise RuntimeError(f"{spec.name} 需要通过 run_tool 执行（缺少运行上下文）")
        return json.dumps(run_tool(ctx, spec.name, kwargs), ensure_ascii=False)

    return StructuredTool.from_function(
        func=_run,
        name=spec.name,
        description=spec.description,
        args_schema=args_schema,
    )


def as_langchain_tools(
    specs: Iterable[ToolSpec], ctx: ToolContext | None = None
) -> list[StructuredTool]:
    return [as_langchain_tool(spec, ctx) for spec in specs]


def tools_for(
    permissions: Iterable[str], *, registry: dict[str, ToolSpec] | None = None
) -> list[ToolSpec]:
    """只把调用者有权限的工具暴露给模型。

    这样模型连"试一试"的机会都没有，比调用后才拒绝更干净；
    真正的兜底校验在 `run_tool` 里，两处都留着。

    `permission` 为空串表示登录即可（例如基础字典这类配置数据），对所有登录用户开放。
    """
    granted = set(permissions)
    specs = (registry or default_registry()).values()
    return [spec for spec in specs if not spec.permission or spec.permission in granted]


def run_tool(
    ctx: ToolContext,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    registry: dict[str, ToolSpec] | None = None,
) -> dict[str, Any]:
    """执行一次工具调用，返回结构化结果（含错误），并写审计。

    registry 允许调用方追加自己的工具（例如诊断工具需要注入模型客户端、
    MCP Server 需要额外暴露几个只读工具），而不必改默认注册表。
    """
    started = time.perf_counter()
    arguments = arguments if isinstance(arguments, dict) else {}
    spec = (registry or default_registry()).get(name)

    if spec is None:
        return {"ok": False, "tool": name, "error": f"没有名为 {name} 的工具"}
    if spec.permission and spec.permission not in ctx.permissions:
        return {"ok": False, "tool": name, "error": "当前账号没有该数据的查看权限"}

    try:
        data = spec.handler(ctx, arguments)
        result: dict[str, Any] = {"ok": True, "tool": name, **data}
    except BusinessError as exc:
        result = {"ok": False, "tool": name, "error": exc.message}
    except Exception:  # 工具失败不能让整轮问答崩掉，交给模型向用户说明
        logger.exception("工具 %s 执行失败", name)
        result = {"ok": False, "tool": name, "error": "查询失败，请稍后重试"}

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    result["elapsed_ms"] = elapsed_ms
    record_audit(
        ctx.db,
        user_id=ctx.user.id,
        username=ctx.user.username,
        action=f"ai.tool.{name}",
        object_type="ai_tool",
        detail=json.dumps(
            {"arguments": arguments, "ok": result["ok"], "elapsed_ms": elapsed_ms},
            ensure_ascii=False,
        )[:500],
        client_ip=ctx.client_ip,
    )
    return result
