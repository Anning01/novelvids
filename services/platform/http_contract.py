"""HTTP behavior for the public SDK surface."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)
_upstream_context = ContextVar("public_upstream_response", default=None)


def error_body(status: int, message: str, param: str | None = None) -> dict:
    error_type, code = {
        401: ("invalid_request_error", "invalid_api_key"),
        402: ("insufficient_quota", "insufficient_quota"),
        403: ("permission_error", None),
        404: ("invalid_request_error", "model_not_found" if param == "model" else None),
        429: ("rate_limit_error", "rate_limit_exceeded"),
    }.get(status, ("server_error" if status >= 500 else "invalid_request_error", None))
    return {"error": {"message": message, "type": error_type, "param": param, "code": code}}


def redact_secret(content: bytes, secret: str) -> bytes:
    if not secret:
        return content
    for value in {secret, json.dumps(secret, ensure_ascii=True)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]}:
        content = content.replace(value.encode(), b"[redacted]")
    return content


class UpstreamResponseError(Exception):
    def __init__(self, response: httpx.Response, request_id: str, secret: str = ""):
        self.status = response.status_code
        self.content = redact_secret(response.content, secret)
        self.headers = {name: response.headers[name] for name in ("content-type", "retry-after", "x-request-id")
                        if name in response.headers}
        self.headers.setdefault("x-request-id", request_id)
        self.headers["x-novelvids-request-id"] = request_id
        self.headers["cache-control"] = "no-store"
        super().__init__(f"Upstream HTTP {self.status}")


@contextmanager
def public_upstream(request_id: str, secret: str):
    token = _upstream_context.set((request_id, secret))
    try:
        yield
    finally:
        _upstream_context.reset(token)


def check_upstream_response(response: httpx.Response) -> None:
    context = _upstream_context.get()
    if context is not None and response.status_code >= 400:
        raise UpstreamResponseError(response, *context)


class DeveloperRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                from services.platform.request_data import bounded_json_body
                await bounded_json_body(request)
                return await handler(request)
            except UpstreamResponseError as error:
                logger.warning("Developer API upstream rejected request path=%s status=%d request_id=%s upstream_request_id=%s",
                               self.path, error.status, error.headers["x-novelvids-request-id"], error.headers["x-request-id"])
                return Response(error.content, status_code=error.status, headers=error.headers)
            except HTTPException as error:
                return JSONResponse(error_body(error.status_code, str(error.detail)),
                                    status_code=error.status_code, headers=error.headers)
            except RequestValidationError as error:
                field = error.errors()[0]
                param = ".".join(str(part) for part in field["loc"][1:]) or None
                return JSONResponse(error_body(422, field["msg"], param), status_code=422)

        return handle


def public_task_error(payload: dict, fallback):
    """Keep native task failures on the developer surface; studio UI keeps its own presentation."""
    context = _upstream_context.get()
    if context is None:
        return fallback
    original = payload.get("error")
    if not isinstance(original, dict):
        original = {"code":payload.get("code"), "message":payload.get("message") or original or fallback}
    return json.loads(redact_secret(json.dumps(original, ensure_ascii=False).encode(), context[1]))


async def developer_http_error(request: Request, error):
    return JSONResponse(error_body(error.status_code, str(error.detail)), status_code=error.status_code, headers=error.headers)


async def developer_internal_error(request: Request, error):
    logger.error("Developer API internal failure path=%s type=%s", request.url.path, type(error).__name__)
    return JSONResponse(error_body(500, "Internal server error"), status_code=500)


DEVELOPER_EXCEPTION_HANDLERS = {StarletteHTTPException:developer_http_error, Exception:developer_internal_error}
