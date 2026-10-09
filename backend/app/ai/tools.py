"""Agent 工具层：把现有业务查询包装成模型可调用的工具。

三条约定，都是这个项目里已经存在的规矩在 AI 侧的延续：

1. **不另写查询。** 工具调用现有 service 函数，权限与业务口径跟着现有实现走，
   AI 模块里不出现一句 SQL；
2. **权限先于调用。** 用户没有某工具对应的权限点，这个工具根本不暴露给模型
   （见 `tools_for`），即使模型坚持要调，`run_tool` 也会再挡一次；
3. **每次调用都留痕。** 审计挂在当前事务上，与业务动作同生共死。

返回给模型的数据一律裁剪成"回答问题够用"的字段：工单步骤清单、备注这类
大对象不进上下文，既省 token，也不把无关业务数据带出去。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.audit import record_audit
from app.core.errors import BusinessError
from app.models.user import User
from app.services import consumable as consumable_service
from app.services import dict as dict_service
from app.services import equipment as equipment_service
from app.services import fault as fault_service
from app.services import maintenance as maintenance_service
from app.services import report as report_service
from app.services import well_operation as operation_service

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


@dataclass(frozen=True)
class ToolContext:
    """一次工具调用需要的东西：会话、调用者、调用者权限、来源 IP。"""

    db: Session
    user: User
    permissions: frozenset[str]
    client_ip: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]

    @property
    def schema(self) -> dict[str, Any]:
        """OpenAI function calling 的工具描述。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ----------------------------------------------------------------- 参数处理


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


def _decimal(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stamp(value: Any) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else None


def resolve_equipment_id(ctx: ToolContext, equipment_no: str | None) -> int | None:
    """按脉冲编号精确匹配设备；匹配不到返回 None，由调用方如实告知模型。"""
    if not equipment_no:
        return None
    items, _ = equipment_service.list_equipment(ctx.db, keyword=equipment_no, page_size=5)
    for item in items:
        if item.equipment_no == equipment_no:
            return item.id
    return items[0].id if len(items) == 1 else None


# ----------------------------------------------------------------- 工具实现


def _query_equipment(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    items, total = equipment_service.list_equipment(
        ctx.db,
        keyword=_text(arguments.get("keyword")),
        status=_text(arguments.get("status"), max_length=16),
        page=1,
        page_size=_limit(arguments.get("limit")),
    )
    return {
        "total": total,
        "items": [
            {
                "equipment_no": item.equipment_no,
                "model": item.model,
                "status": item.status,
                "total_run_hours": _decimal(item.total_run_hours),
                "total_run_count": item.total_run_count,
                "last_maintenance_at": _stamp(item.last_maintenance_at),
                "company": item.company,
            }
            for item in items
        ],
    }


def _query_fault_history(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    equipment_no = _text(arguments.get("equipment_no"))
    equipment_id = resolve_equipment_id(ctx, equipment_no)
    if equipment_no and equipment_id is None:
        return {"total": 0, "items": [], "note": f"没有找到编号为 {equipment_no} 的设备"}

    items, total = fault_service.list_faults(
        ctx.db,
        equipment_id=equipment_id,
        fault_type=_text(arguments.get("fault_type")),
        status=_text(arguments.get("status"), max_length=16),
        page=1,
        page_size=_limit(arguments.get("limit")),
    )
    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "equipment_no": item.equipment_no,
                "occurred_at": _stamp(item.occurred_at),
                "position": item.position,
                "fault_type": item.fault_type,
                "description": item.description,
                "cause": item.cause,
                "solution": item.solution,
                "status": item.status,
            }
            for item in items
        ],
    }


def _query_maintenance_orders(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    equipment_no = _text(arguments.get("equipment_no"))
    equipment_id = resolve_equipment_id(ctx, equipment_no)
    if equipment_no and equipment_id is None:
        return {"total": 0, "items": [], "note": f"没有找到编号为 {equipment_no} 的设备"}

    items, total = maintenance_service.list_orders(
        ctx.db,
        equipment_id=equipment_id,
        level=_text(arguments.get("level"), max_length=16),
        status=_text(arguments.get("status"), max_length=16),
        page=1,
        page_size=_limit(arguments.get("limit")),
    )
    return {
        "total": total,
        "items": [
            {
                "order_no": item.order_no,
                "equipment_no": item.equipment_no,
                "level": item.level,
                "status": item.status,
                "start_date": str(item.start_date) if item.start_date else None,
                "end_date": str(item.end_date) if item.end_date else None,
                "result": item.result,
                "suggestion": item.suggestion,
            }
            for item in items
        ],
    }


def _query_consumables(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    items, total = consumable_service.list_consumables(
        ctx.db,
        keyword=_text(arguments.get("keyword")),
        low_stock_only=_flag(arguments.get("low_stock_only")),
        page=1,
        page_size=_limit(arguments.get("limit")),
    )
    return {
        "total": total,
        "low_stock_count": sum(1 for item in items if item.quantity <= item.safety_stock),
        "items": [
            {
                "part_no": item.part_no,
                "description": item.description,
                "quantity": item.quantity,
                "safety_stock": item.safety_stock,
                "unit": item.unit,
                "low_stock": item.quantity <= item.safety_stock,
            }
            for item in items
        ],
    }


def _query_well_operations(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    equipment_no = _text(arguments.get("equipment_no"))
    equipment_id = resolve_equipment_id(ctx, equipment_no)
    if equipment_no and equipment_id is None:
        return {"total": 0, "items": [], "note": f"没有找到编号为 {equipment_no} 的设备"}

    items, total = operation_service.list_operations(
        ctx.db,
        equipment_id=equipment_id,
        well_no=_text(arguments.get("well_no")),
        page=1,
        page_size=_limit(arguments.get("limit")),
    )
    return {
        "total": total,
        "items": [
            {
                "equipment_no": item.equipment_no,
                "well_no": item.well_no,
                "start_date": _stamp(item.start_date),
                "end_date": _stamp(item.end_date),
                "run_hours": _decimal(item.run_hours),
                "footage": _decimal(item.footage),
                "instrument_type": item.instrument_type,
                "operator_name": item.operator_name,
            }
            for item in items
        ],
    }


def _query_overview(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """整体概览：设备规模、待维保、低库存、未解决故障。"""
    data = report_service.dashboard(ctx.db)
    return {
        "equipment_total": data.get("equipment_total"),
        "status_counts": data.get("status_counts"),
        "maintenance_due": data.get("maintenance_due"),
        "low_stock_consumables": data.get("low_stock_consumables"),
        "open_faults": data.get("open_faults"),
    }


def _query_dict_items(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """基础字典：设备状态、仪器类型、故障类型、维保等级等可选取值。

    这是纯配置数据，不涉及业务记录，所以不挂业务权限点（`permission=""` 表示登录即可），
    但**仍然走同一套工具层**：一样写审计、一样受 MCP 的身份约束。
    """
    from app.models.system import DictItem

    category = _text(arguments.get("category"), max_length=32)
    if category:
        categories = [category]
    else:
        categories = list(
            ctx.db.execute(
                select(DictItem.category).distinct().order_by(DictItem.category)
            ).scalars()
        )
    return {"items": {name: dict_service.options(ctx.db, name) for name in categories}}


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="query_overview",
        description="查询系统整体概览：设备总数与状态分布、待维保设备数、低库存耗材数、未解决故障数。适合回答“整体情况怎么样”这类问题。",
        permission="report.view",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_query_overview,
    ),
    ToolSpec(
        name="query_dict_items",
        description=(
            "查询基础字典的可选取值：设备状态、仪器类型、故障类型、维保等级、故障处理状态。"
            "调用其它工具前如果不确定取值，先用它确认。"
        ),
        # 纯配置数据，登录即可读；空串表示不挂业务权限点
        permission="",
        parameters={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "字典分类，留空返回全部分类"},
            },
            "required": [],
        },
        handler=_query_dict_items,
    ),
    ToolSpec(
        name="query_equipment",
        description="按编号关键字或状态查询设备台账，返回编号、型号、状态、累计使用时长与次数、最近维保时间。",
        permission="equipment.view",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "按脉冲编号或型号模糊匹配"},
                "status": {"type": "string", "description": "设备状态：在用、待命、维保、报废"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最多 50"},
            },
            "required": [],
        },
        handler=_query_equipment,
    ),
    ToolSpec(
        name="query_fault_history",
        description="查询故障记录：现象、原因、解决方案与处理状态，可按设备编号、故障类型、状态过滤。",
        permission="fault.view",
        parameters={
            "type": "object",
            "properties": {
                "equipment_no": {"type": "string", "description": "脉冲编号，如 YST-48R-001"},
                "fault_type": {"type": "string", "description": "故障类型，取值来自字典"},
                "status": {"type": "string", "description": "处理状态：待处理、处理中、已解决"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最多 50"},
            },
            "required": [],
        },
        handler=_query_fault_history,
    ),
    ToolSpec(
        name="query_maintenance_orders",
        description="查询维保工单：工单号、维保等级、状态、起止日期、维保结果与建议。",
        permission="maintenance.view",
        parameters={
            "type": "object",
            "properties": {
                "equipment_no": {"type": "string", "description": "脉冲编号"},
                "level": {"type": "string", "description": "维保等级：一级维保、二级维保、三级维保、四级维保"},
                "status": {"type": "string", "description": "工单状态：进行中、已完成"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最多 50"},
            },
            "required": [],
        },
        handler=_query_maintenance_orders,
    ),
    ToolSpec(
        name="query_consumables",
        description="查询耗材库存：部件号、中文描述、当前库存、安全库存与是否低库存。",
        permission="consumable.view",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "按部件号或描述模糊匹配"},
                "low_stock_only": {"type": "boolean", "description": "只看低于或等于安全库存的耗材"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最多 50"},
            },
            "required": [],
        },
        handler=_query_consumables,
    ),
    ToolSpec(
        name="query_well_operations",
        description="查询使用记录（下井作业）：井号、入井与出井时间、使用时长、进尺、仪器类型与作业人员。",
        permission="well_operation.view",
        parameters={
            "type": "object",
            "properties": {
                "equipment_no": {"type": "string", "description": "脉冲编号"},
                "well_no": {"type": "string", "description": "井号，模糊匹配"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最多 50"},
            },
            "required": [],
        },
        handler=_query_well_operations,
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {tool.name: tool for tool in TOOLS}


def tools_for(permissions: Iterable[str]) -> list[ToolSpec]:
    """只把调用者有权限的工具暴露给模型。

    这样模型连"试一试"的机会都没有，比调用后才拒绝更干净；
    真正的兜底校验在 `run_tool` 里，两处都留着。

    `permission` 为空串表示登录即可（例如基础字典这类配置数据），对所有登录用户开放。
    """
    granted = set(permissions)
    return [tool for tool in TOOLS if not tool.permission or tool.permission in granted]


def run_tool(
    ctx: ToolContext,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    registry: dict[str, ToolSpec] | None = None,
) -> dict[str, Any]:
    """执行一次工具调用，返回结构化结果（含错误），并写审计。

    registry 允许调用方追加自己的工具（例如诊断工具需要注入模型客户端、
    MCP Server 需要额外暴露几个只读工具），而不必改这张全局注册表。
    """
    started = time.perf_counter()
    arguments = arguments if isinstance(arguments, dict) else {}
    spec = (registry or TOOLS_BY_NAME).get(name)

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
