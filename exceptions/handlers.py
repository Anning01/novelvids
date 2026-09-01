import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from tortoise.exceptions import (
    DoesNotExist,
    IntegrityError,
    ValidationError as TortoiseValidationError,
)

from config import settings
from utils.response_format import ResponseSchema


logger = logging.getLogger(__name__)


# 捕获 HTTPException (比如 404, 401)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    response_data = ResponseSchema(
        code=exc.status_code,
        data=None,
        message=exc.detail or "请求错误",
    )
    # 兼容现有 HTTP 200 + body.code 协议；限流必须保留标准 429，供浏览器、
    # 反向代理与监控正确识别，并透传 Retry-After。
    status_code = exc.status_code if exc.status_code == 429 else 200
    return JSONResponse(
        status_code=status_code,
        content=response_data.model_dump(),
        headers=exc.headers,
    )


# 捕获 FastAPI 422 验证错误
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    error_messages = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        error_messages.append(f"{field}: {error['msg']}")

    message = "; ".join(error_messages)

    response_data = ResponseSchema(
        code=422,
        data=None,
        message=message,
    )
    return JSONResponse(status_code=200, content=response_data.model_dump())


# 捕获数据库相关异常
async def database_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, DoesNotExist):
        response_data = ResponseSchema(
            code=404,
            data=None,
            message="请求的数据不存在",
        )
        return JSONResponse(status_code=200, content=response_data.model_dump())

    elif isinstance(exc, IntegrityError):
        response_data = ResponseSchema(
            code=400,
            data=None,
            message="数据完整性错误，可能存在重复数据或违反约束",
        )
        return JSONResponse(status_code=200, content=response_data.model_dump())

    elif isinstance(exc, TortoiseValidationError):
        response_data = ResponseSchema(
            code=400,
            data=None,
            message=f"数据验证错误: {str(exc)}",
        )
        return JSONResponse(status_code=200, content=response_data.model_dump())
    return JSONResponse(status_code=500, content=str(exc))


# 捕获 Python 所有未处理异常
async def global_exception_handler(request: Request, exc: Exception):
    if settings.EXPOSE_INTERNAL_ERRORS:
        message = str(exc) or "服务器内部错误，请联系管理员"
        logger.error(
            "Unhandled %s during %s %s: %s",
            type(exc).__name__,
            request.method,
            request.url.path,
            exc,
        )
    else:
        message = "服务器内部错误，请联系管理员"
        # 生产环境不记录异常正文，避免上游响应、密钥或用户数据进入日志。
        logger.error(
            "Unhandled %s during %s %s",
            type(exc).__name__,
            request.method,
            request.url.path,
        )
    response_data = ResponseSchema(
        code=500,
        data=None,
        message=message,
    )
    return JSONResponse(status_code=500, content=response_data.model_dump())
