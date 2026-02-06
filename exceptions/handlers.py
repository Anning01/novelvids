from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from tortoise.exceptions import (
    DoesNotExist,
    IntegrityError,
    ValidationError as TortoiseValidationError,
)

from utils.response_format import ResponseSchema


# 捕获 HTTPException (比如 404, 401)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    response_data = ResponseSchema(
        code=exc.status_code,
        data=None,
        message=exc.detail or "请求错误",
    )
    return JSONResponse(status_code=200, content=response_data.model_dump())


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
    response_data = ResponseSchema(
        code=500,
        data=None,
        message=str(exc) or "服务器内部错误，请联系管理员",
    )
    return JSONResponse(status_code=500, content=response_data.model_dump())
