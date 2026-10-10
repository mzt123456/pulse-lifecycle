"""工具定义：用 LangChain 的 @tool 写，参数 schema 由类型注解与 docstring 自动推导。

改成 @tool 之前，这里的参数 JSON Schema 是手写的，容易和实现漂移（参数名改了忘了改 schema，
校验规则写了两遍）。现在：

- **描述**来自函数 docstring，**参数**来自类型注解，schema 由 Pydantic 生成；
- 运行上下文（数据库会话、调用者、来源 IP）用 `InjectedToolArg` 注入，
  `convert_to_openai_tool` 会把它从模型可见的参数里剔除——模型看不到，也不可能伪造；
- 参数由 Pydantic 校验，类型不对直接报错并交回模型，不用在函数体里写一堆 isinstance。

**执行、权限校验与审计仍然在 `tools.run_tool` 里。** @tool 只负责"怎么定义工具"，
业务约束不交给框架：同一份定义同时供 HTTP 接口、LangGraph 编排、MCP 出口与手写循环使用。
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.ai.tools import (
    MAX_LIMIT,
    ToolContext,
    ToolSpec,
    _flag,
    _limit,
    _text,
    resolve_equipment_id,
)
from app.services import consumable as consumable_service
from app.services import dict as dict_service
from app.services import equipment as equipment_service
from app.services import fault as fault_service
from app.services import maintenance as maintenance_service
from app.services import report as report_service
from app.services import well_operation as operation_service


@tool
def query_overview(context: Annotated[ToolContext, InjectedToolArg]) -> dict:
    """查询系统整体概览：设备总数与状态分布、待维保设备数、低库存耗材数、未解决故障数。适合回答“整体情况怎么样”这类问题。"""
    data = report_service.dashboard(context.db)
    return {
        "equipment_total": data.get("equipment_total"),
        "status_counts": data.get("status_counts"),
        "maintenance_due": data.get("maintenance_due"),
        "low_stock_consumables": data.get("low_stock_consumables"),
        "open_faults": data.get("open_faults"),
    }


@tool(parse_docstring=True)
def query_equipment(
    context: Annotated[ToolContext, InjectedToolArg],
    keyword: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> dict:
    """按编号关键字或状态查询设备台账，返回编号、型号、状态、累计使用时长与次数、最近维保时间。

    Args:
        keyword: 按脉冲编号或型号模糊匹配。
        status: 设备状态，取值：在用、待命、维保、报废。
        limit: 返回条数，默认 10，最多 50。
    """
    items, total = equipment_service.list_equipment(
        context.db,
        keyword=_text(keyword),
        status=_text(status, max_length=16),
        page=1,
        page_size=_limit(limit),
    )
    return {
        "total": total,
        "items": [
            {
                "equipment_no": item.equipment_no,
                "model": item.model,
                "status": item.status,
                "total_run_hours": float(item.total_run_hours) if item.total_run_hours is not None else None,
                "total_run_count": item.total_run_count,
                "last_maintenance_at": (
                    item.last_maintenance_at.strftime("%Y-%m-%d %H:%M:%S")
                    if item.last_maintenance_at
                    else None
                ),
                "company": item.company,
            }
            for item in items
        ],
    }


@tool(parse_docstring=True)
def query_fault_history(
    context: Annotated[ToolContext, InjectedToolArg],
    equipment_no: str | None = None,
    fault_type: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> dict:
    """查询故障记录：现象、原因、解决方案与处理状态，可按设备编号、故障类型、状态过滤。

    Args:
        equipment_no: 脉冲编号，例如 YST-48R-001。
        fault_type: 故障类型，取值来自系统字典。
        status: 处理状态，取值：待处理、处理中、已解决。
        limit: 返回条数，默认 10，最多 50。
    """
    equipment_no = _text(equipment_no)
    equipment_id = resolve_equipment_id(context, equipment_no)
    if equipment_no and equipment_id is None:
        return {"total": 0, "items": [], "note": f"没有找到编号为 {equipment_no} 的设备"}

    items, total = fault_service.list_faults(
        context.db,
        equipment_id=equipment_id,
        fault_type=_text(fault_type),
        status=_text(status, max_length=16),
        page=1,
        page_size=_limit(limit),
    )
    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "equipment_no": item.equipment_no,
                "occurred_at": item.occurred_at.strftime("%Y-%m-%d %H:%M:%S") if item.occurred_at else None,
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


@tool(parse_docstring=True)
def query_maintenance_orders(
    context: Annotated[ToolContext, InjectedToolArg],
    equipment_no: str | None = None,
    level: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> dict:
    """查询维保工单：工单号、维保等级、状态、起止日期、维保结果与建议。

    Args:
        equipment_no: 脉冲编号。
        level: 维保等级，取值：一级维保、二级维保、三级维保、四级维保。
        status: 工单状态，取值：进行中、已完成。
        limit: 返回条数，默认 10，最多 50。
    """
    equipment_no = _text(equipment_no)
    equipment_id = resolve_equipment_id(context, equipment_no)
    if equipment_no and equipment_id is None:
        return {"total": 0, "items": [], "note": f"没有找到编号为 {equipment_no} 的设备"}

    items, total = maintenance_service.list_orders(
        context.db,
        equipment_id=equipment_id,
        level=_text(level, max_length=16),
        status=_text(status, max_length=16),
        page=1,
        page_size=_limit(limit),
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


@tool(parse_docstring=True)
def query_consumables(
    context: Annotated[ToolContext, InjectedToolArg],
    keyword: str | None = None,
    low_stock_only: bool = False,
    limit: int = 10,
) -> dict:
    """查询耗材库存：部件号、中文描述、当前库存、安全库存与是否低库存。

    Args:
        keyword: 按部件号或描述模糊匹配。
        low_stock_only: 只看低于或等于安全库存的耗材。
        limit: 返回条数，默认 10，最多 50。
    """
    items, total = consumable_service.list_consumables(
        context.db,
        keyword=_text(keyword),
        low_stock_only=_flag(low_stock_only),
        page=1,
        page_size=_limit(limit),
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


@tool(parse_docstring=True)
def query_well_operations(
    context: Annotated[ToolContext, InjectedToolArg],
    equipment_no: str | None = None,
    well_no: str | None = None,
    limit: int = 10,
) -> dict:
    """查询使用记录（下井作业）：井号、入井与出井时间、使用时长、进尺、仪器类型与作业人员。

    Args:
        equipment_no: 脉冲编号。
        well_no: 井号，模糊匹配。
        limit: 返回条数，默认 10，最多 50。
    """
    equipment_no = _text(equipment_no)
    equipment_id = resolve_equipment_id(context, equipment_no)
    if equipment_no and equipment_id is None:
        return {"total": 0, "items": [], "note": f"没有找到编号为 {equipment_no} 的设备"}

    items, total = operation_service.list_operations(
        context.db,
        equipment_id=equipment_id,
        well_no=_text(well_no),
        page=1,
        page_size=_limit(limit),
    )
    return {
        "total": total,
        "items": [
            {
                "equipment_no": item.equipment_no,
                "well_no": item.well_no,
                "start_date": item.start_date.strftime("%Y-%m-%d %H:%M:%S") if item.start_date else None,
                "end_date": item.end_date.strftime("%Y-%m-%d %H:%M:%S") if item.end_date else None,
                "run_hours": float(item.run_hours) if item.run_hours is not None else None,
                "footage": float(item.footage) if item.footage is not None else None,
                "instrument_type": item.instrument_type,
                "operator_name": item.operator_name,
            }
            for item in items
        ],
    }


@tool(parse_docstring=True)
def query_dict_items(
    context: Annotated[ToolContext, InjectedToolArg],
    category: str | None = None,
) -> dict:
    """查询基础字典的可选取值：设备状态、仪器类型、故障类型、维保等级、故障处理状态。调用其它工具前如果不确定取值，先用它确认。

    Args:
        category: 字典分类，留空返回全部分类。
    """
    from sqlalchemy import select

    from app.models.system import DictItem

    category = _text(category, max_length=32)
    if category:
        categories = [category]
    else:
        categories = list(
            context.db.execute(select(DictItem.category).distinct().order_by(DictItem.category)).scalars()
        )
    return {"items": {name: dict_service.options(context.db, name) for name in categories}}


def to_spec(tool_obj: Any, permission: str) -> ToolSpec:
    """把 @tool 对象桥接成我们自己的 ToolSpec：schema 取框架生成的，权限与审计留在自己的执行层。"""
    openai_tool = convert_to_openai_tool(tool_obj)
    parameters = openai_tool["function"]["parameters"]
    allowed = set(parameters.get("properties", {}))

    def handler(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        # 模型偶尔会凭空多给参数，过滤掉未知键，避免校验直接失败
        payload = {key: value for key, value in (arguments or {}).items() if key in allowed}
        return tool_obj.invoke({**payload, "context": context})

    return ToolSpec(
        name=tool_obj.name,
        description=tool_obj.description,
        permission=permission,
        parameters=parameters,
        handler=handler,
    )


# 权限点跟着工具走：@tool 本身没有这个概念，在这里显式绑定
TOOLS: tuple[ToolSpec, ...] = (
    to_spec(query_overview, "report.view"),
    to_spec(query_equipment, "equipment.view"),
    to_spec(query_fault_history, "fault.view"),
    to_spec(query_maintenance_orders, "maintenance.view"),
    to_spec(query_consumables, "consumable.view"),
    to_spec(query_well_operations, "well_operation.view"),
    # 纯配置数据，登录即可读（空串表示不挂业务权限点）
    to_spec(query_dict_items, ""),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOLS}

__all__ = ["TOOLS", "TOOLS_BY_NAME", "to_spec", "MAX_LIMIT"]

