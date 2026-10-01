"""错误码、业务异常与全局异常处理，错误码对应编写报告 5.2。"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.response import fail

logger = logging.getLogger(__name__)


class ErrorCode:
    OK = 0
    INVALID_PARAM = 40001
    NOT_AUTHENTICATED = 40100
    TOKEN_EXPIRED = 40101
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    CONFLICT = 40900
    BUSINESS_RULE = 42200
    INTERNAL = 50000


HTTP_STATUS_TO_CODE = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.INVALID_PARAM,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.NOT_AUTHENTICATED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    # Starlette 新版本把该常量改名，这里兼容两种命名。
    getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422): ErrorCode.BUSINESS_RULE,
}

# Starlette 对未显式给出 detail 的异常使用英文短语，这里换成对应的中文提示。
DEFAULT_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "请求参数错误",
    status.HTTP_401_UNAUTHORIZED: "未登录或令牌缺失",
    status.HTTP_403_FORBIDDEN: "无操作权限",
    status.HTTP_404_NOT_FOUND: "对象不存在",
    status.HTTP_405_METHOD_NOT_ALLOWED: "请求方法不允许",
    status.HTTP_409_CONFLICT: "数据冲突",
    422: "业务校验失败",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "服务器内部错误",
}

STARLETTE_PHRASES = {
    "Bad Request",
    "Unauthorized",
    "Forbidden",
    "Not Found",
    "Method Not Allowed",
    "Conflict",
    "Unprocessable Entity",
    "Internal Server Error",
}


class BusinessError(Exception):
    """业务异常：带错误码与面向用户的提示，由服务层抛出。"""

    def __init__(
        self,
        code: int,
        message: str,
        http_status: int = status.HTTP_400_BAD_REQUEST,
        data: object = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data


def register_exception_handlers(app: FastAPI) -> None:
    """把各类异常统一收敛成 {code, message, data}。"""

    @app.exception_handler(BusinessError)
    async def handle_business_error(_: Request, exc: BusinessError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=fail(exc.code, exc.message, exc.data),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in item.get("loc", [])), "reason": item.get("msg", "")}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=fail(ErrorCode.INVALID_PARAM, "请求参数错误", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_STATUS_TO_CODE.get(exc.status_code)
        if code is None:  # 未逐一列出的状态码按 4xx / 5xx 归类
            code = ErrorCode.INVALID_PARAM if 400 <= exc.status_code < 500 else ErrorCode.INTERNAL
        detail = exc.detail
        if isinstance(detail, str) and detail not in STARLETTE_PHRASES:
            message = detail
        else:
            message = DEFAULT_MESSAGES.get(exc.status_code, "请求失败")
        return JSONResponse(status_code=exc.status_code, content=fail(code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理的异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=fail(ErrorCode.INTERNAL, "服务器内部错误"),
        )
