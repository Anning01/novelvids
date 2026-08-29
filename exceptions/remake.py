from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from utils.response_format import ResponseSchema


class RemakeError(Exception):
    """重制工坊稳定业务错误。"""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.context = context or {}
        self.retryable = retryable


async def remake_exception_handler(_: Request, exc: RemakeError) -> JSONResponse:
    payload = ResponseSchema(
        code=exc.status_code,
        data={
            "error_code": exc.error_code,
            "context": exc.context,
            "retryable": exc.retryable,
        },
        message=exc.message,
    )
    # 与项目现有异常契约保持一致：协议状态为 200，业务状态在响应体 code。
    return JSONResponse(status_code=200, content=payload.model_dump())
