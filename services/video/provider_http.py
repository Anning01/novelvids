"""视频供应商 HTTP 边界共享的脱敏解析工具。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


def safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def request_id(response: httpx.Response) -> str | None:
    for name in ("x-request-id", "request-id", "x-volc-request-id", "trace-id"):
        if value := response.headers.get(name):
            return value[:120]
    return None


def provider_error(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or error.get("type") or "PROVIDER_ERROR")[:80]
        message = str(error.get("message") or "视频生成任务失败")[:500]
        return f"{message}（{code}）"
    if isinstance(error, str) and error.strip():
        return error.strip()[:500]
    message = data.get("message") or data.get("detail")
    if isinstance(message, str) and message.strip():
        code = data.get("code") or data.get("type")
        normalized_message = message.strip()[:500]
        if code is not None and str(code).strip():
            return f"{normalized_message}（{str(code).strip()[:80]}）"
        return normalized_message
    return None


def http_provider_error(response: httpx.Response) -> str | None:
    """只提取结构化错误，避免 HTML 或请求正文进入业务日志。"""
    try:
        return provider_error(response.json())
    except ValueError:
        return None


def video_url(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("video_url", "url"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("url")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    content = data.get("content")
    if isinstance(content, dict):
        return video_url(content)
    if isinstance(content, list):
        for item in content:
            if url := video_url(item):
                return url
    return None


def last_frame_url(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("last_frame_url", "last_frame"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("url")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    content = data.get("content")
    if isinstance(content, dict):
        return last_frame_url(content)
    if isinstance(content, list):
        for item in content:
            if url := last_frame_url(item):
                return url
    return None
