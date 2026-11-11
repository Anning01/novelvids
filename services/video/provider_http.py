"""视频供应商 HTTP 边界共享的脱敏解析工具。"""

from __future__ import annotations

from utils.messages import localized_message

from typing import Any
from urllib.parse import urlsplit, urlunsplit
import re

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
        message = str(error.get("message") or localized_message('视频生成任务失败'))[:500]
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


def public_provider_error(
    data: Any, *, status_code: int | None = None, transport_request_id: str | None = None,
    secrets: tuple[str, ...] = (),
) -> str:
    """Keep recognized failure facts, never arbitrary provider text or media URLs."""
    payload = data if isinstance(data, dict) else {}
    error = payload.get("error")
    fields = error if isinstance(error, dict) else {}
    metadata = fields.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    detail = provider_error(payload) or ""
    raw_message = str(fields.get("message") or error or payload.get("message") or "")
    lowered = detail.casefold()
    params = list(dict.fromkeys(re.findall(
        r"content\[\d{1,4}\](?:\.(?:image_uri|image_url|video_url))?",
        str(fields.get("param") or detail),
    )))
    code = None
    if "OutputVideoSensitiveContentDetected" in detail or "output video may contain sensitive information" in lowered:
        code, message = "OutputVideoSensitiveContentDetected", "output video may contain sensitive information"
    elif "InputImageSensitiveContentDetected.PrivacyInformation" in detail or "may contain real person" in lowered:
        code = "InputImageSensitiveContentDetected.PrivacyInformation"
        message = "input image " + " ".join(f"'{param}'" for param in params) + " may contain real person"
    elif "resource download failed" in lowered or (
        any(name in lowered for name in ("image_uri", "video_url")) and "not valid" in lowered
    ):
        original_code = re.search(r"\bInvalidParameter(?:Value)?\b", detail)
        code = original_code[0] if original_code else "ResourceDownloadFailed"
        message = "resource download failed: " + " ".join(params)
    else:
        message = localized_message('视频生成失败，请检查生成内容或联系管理员')

    body_request_id = re.search(r"(?:Request id:\s*|request_id[=:]\s*[\"']?)([A-Za-z0-9_-]{1,120})(?=$|[\s.,\"'）})])", raw_message, re.I)
    candidates = (fields.get("request_id"), metadata.get("request_id"), payload.get("request_id"),
        body_request_id[1] if body_request_id else None, transport_request_id)
    trace = next((value for value in candidates if isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value)
        and not re.match(r"(?:sk|ark|secret)[-_]", value, re.I)
        and not any(secret and secret in value for secret in secrets)), None)
    original_status = re.search(r"\bHTTP\s*([45]\d{2})\b", raw_message, re.I)
    status = int(original_status[1]) if original_status else status_code
    status = status if isinstance(status, int) and 400 <= status < 600 else None
    if trace and status is None:
        message += f" Request id: {trace}"
    if code:
        message += f"（{code}）"
    if status:
        message += f"（HTTP {status}" + (f"，request_id={trace}" if trace else "") + "）"
    return message


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
