"""统一响应结构：{code, message, data}，code 为 0 表示成功。"""

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """接口统一返回结构，与编写报告 5.1 的约定一致。"""

    code: int = 0
    message: str = "ok"
    data: Any = None


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str, data: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}
