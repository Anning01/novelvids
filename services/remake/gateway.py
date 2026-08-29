"""重制工坊多模态视频理解模型边界。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from services.llm.json_output import completion_usage

MAX_MODEL_VIDEO_BYTES = 35_000_000
VIDEO_INPUT_FPS = 1.0
ANALYSIS_TIMEOUT_SECONDS = 600.0
ANALYSIS_ERROR_CODE = "REMAKE_VIDEO_ANALYSIS_FAILED"

logger = logging.getLogger(__name__)


class RemakeVideoAnalysisError(RuntimeError):
    """对外稳定且不包含供应商响应、Prompt 或密钥的模型错误。"""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = ANALYSIS_ERROR_CODE,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.error_code = error_code
        self.user_message = message
        super().__init__(f"{message}（错误代码：{error_code}）")
        self.usage = usage or {}


class RemakeVideoAnalysisGateway:
    """使用 OpenAI-compatible Chat Completions 分析本地视频。"""

    def __init__(
        self,
        config: Any,
        *,
        client: Any | None = None,
        client_factory: Callable[..., Any] = AsyncOpenAI,
        retry_delays: tuple[float, ...] = (1.0, 2.0),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.client = client or client_factory(
            base_url=str(config.base_url).rstrip("/"),
            api_key=config.api_key,
            timeout=ANALYSIS_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.retry_delays = retry_delays
        self.clock = clock
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.timings: list[dict[str, Any]] = []

    async def analyze_many(
        self,
        paths: list[Path],
        *,
        prompt: str,
        schema_name: str,
        response_schema: dict[str, Any],
        context_builder: Callable[[int], str] | None = None,
        on_completed: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(max(1, int(self.config.concurrency or 1)))
        completion_lock = asyncio.Lock()
        completed = 0

        async def analyze(index: int, path: Path) -> dict[str, Any]:
            nonlocal completed
            async with semaphore:
                result = await self.analyze_one(
                    index=index,
                    path=path,
                    prompt=prompt,
                    context=context_builder(index) if context_builder else "",
                    schema_name=schema_name,
                    response_schema=response_schema,
                )
            if on_completed is not None:
                async with completion_lock:
                    completed += 1
                    await on_completed(completed, len(paths))
            return result

        return list(
            await asyncio.gather(
                *(analyze(index, path) for index, path in enumerate(paths, start=1))
            )
        )

    async def analyze_one(
        self,
        *,
        index: int,
        path: Path,
        prompt: str,
        schema_name: str,
        response_schema: dict[str, Any],
        context: str = "",
        include_segment_metadata: bool = True,
    ) -> dict[str, Any]:
        started_at = self.clock()
        video_input = await asyncio.to_thread(self._build_video_input, path)
        instruction = prompt
        if context:
            instruction += f"\n\n{context}"
        if include_segment_metadata:
            instruction += f"\n\n当前片段序号：{index}。只返回约定 JSON。"
        else:
            instruction += "\n\n只返回约定 JSON。"
        instruction += (
            "\n\nJSON 必须严格符合以下 Schema，不要输出 Markdown、解释或思考过程：\n"
            + json.dumps(response_schema, ensure_ascii=False, separators=(",", ":"))
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    video_input,
                ],
            }
        ]
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
        }
        if bool(getattr(self.config, "supports_json_output", False)):
            request["response_format"] = {"type": "json_object"}
        thinking = getattr(self.config, "thinking", None)
        if thinking in {"enabled", "disabled"}:
            request["extra_body"] = {"thinking": {"type": thinking}}
            if thinking == "enabled":
                request["reasoning_effort"] = "minimal"
        if getattr(self.config, "max_tokens", None) is not None:
            request["max_tokens"] = self.config.max_tokens

        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            try:
                completion = await self.client.chat.completions.create(**request)
                self._add_usage(completion_usage(completion))
                result = _completion_json(completion)
                if include_segment_metadata:
                    result.update({"shot_index": index, "file": path.name})
                self._record_timing(
                    index=index,
                    schema_name=schema_name,
                    started_at=started_at,
                    attempts=attempt + 1,
                    status="completed",
                )
                return result
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if attempt >= attempts - 1 or not _is_retryable(error):
                    self._record_timing(
                        index=index,
                        schema_name=schema_name,
                        started_at=started_at,
                        attempts=attempt + 1,
                        status="failed",
                    )
                    _log_provider_failure(
                        error,
                        model=str(self.config.model),
                        schema_name=schema_name,
                        attempt=attempt + 1,
                    )
                    message, error_code = _provider_failure(error, index=index)
                    raise RemakeVideoAnalysisError(
                        message,
                        error_code=error_code,
                        usage=dict(self.usage),
                    ) from None
                await asyncio.sleep(self.retry_delays[attempt])
        raise RemakeVideoAnalysisError("视频片段分析未完成", usage=dict(self.usage))

    def _record_timing(
        self,
        *,
        index: int,
        schema_name: str,
        started_at: float,
        attempts: int,
        status: str,
    ) -> None:
        duration_ms = max(0, round((self.clock() - started_at) * 1000))
        timing = {
            "index": index,
            "schema_name": schema_name,
            "duration_ms": duration_ms,
            "attempts": attempts,
            "status": status,
        }
        self.timings.append(timing)
        logger.info(
            "remake_analysis_request_timing model=%s schema=%s index=%s "
            "duration_ms=%s attempts=%s status=%s",
            str(self.config.model),
            schema_name,
            index,
            duration_ms,
            attempts,
            status,
        )

    def _build_video_input(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise RemakeVideoAnalysisError(
                "模型输入视频不存在",
                error_code="REMAKE_ANALYSIS_MEDIA_MISSING",
            )
        raw_size = path.stat().st_size
        if raw_size > MAX_MODEL_VIDEO_BYTES:
            raise RemakeVideoAnalysisError(
                f"模型输入视频超过 {MAX_MODEL_VIDEO_BYTES} 字节上限",
                error_code="REMAKE_ANALYSIS_MEDIA_TOO_LARGE",
            )
        mime = "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "type": "video_url",
            "video_url": {
                "url": f"data:{mime};base64,{encoded}",
                "fps": VIDEO_INPUT_FPS,
            },
        }

    def _add_usage(self, usage: dict[str, int]) -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.usage[key] += int(usage.get(key, 0) or 0)


def _is_retryable(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        return True
    return status_code in {408, 409, 429} or status_code >= 500


def _provider_failure(error: Exception, *, index: int) -> tuple[str, str]:
    status_code = getattr(error, "status_code", None)
    if status_code == 400:
        return "视频分析请求与当前模型能力不兼容", "REMAKE_ANALYSIS_REQUEST_INVALID"
    if status_code in {401, 403}:
        return "视频分析模型鉴权失败或尚未开通", "REMAKE_ANALYSIS_AUTH_FAILED"
    if status_code == 404:
        return "视频分析模型不存在或不可用", "REMAKE_ANALYSIS_MODEL_NOT_FOUND"
    if status_code == 429:
        return "视频分析模型请求过于频繁，请稍后重试", "REMAKE_ANALYSIS_RATE_LIMITED"
    if isinstance(status_code, int) and status_code >= 500:
        return "视频分析服务暂时不可用", "REMAKE_ANALYSIS_PROVIDER_UNAVAILABLE"
    error_type = type(error).__name__.lower()
    if "connection" in error_type or "timeout" in error_type:
        return "无法连接视频分析服务", "REMAKE_ANALYSIS_CONNECTION_FAILED"
    return f"第 {index} 个视频片段分析失败", ANALYSIS_ERROR_CODE


def _log_provider_failure(
    error: Exception,
    *,
    model: str,
    schema_name: str,
    attempt: int,
) -> None:
    """只记录排错元数据，不记录供应商响应正文、视频、Prompt 或密钥。"""
    status_code = getattr(error, "status_code", None)
    request_id = getattr(error, "request_id", None)
    body = getattr(error, "body", None)
    provider_code = None
    if isinstance(body, dict):
        provider_code = body.get("code")
        nested = body.get("error")
        if provider_code is None and isinstance(nested, dict):
            provider_code = nested.get("code") or nested.get("type")
    logger.warning(
        "remake_analysis_provider_error model=%s schema=%s status=%s code=%s "
        "request_id=%s error_type=%s attempt=%s",
        model,
        schema_name,
        status_code if isinstance(status_code, int) else "-",
        str(provider_code)[:80] if provider_code else "-",
        str(request_id)[:120] if request_id else "-",
        type(error).__name__,
        attempt,
    )


def _completion_json(completion: Any) -> dict[str, Any]:
    choice = completion.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise ValueError("模型输出被截断")
    message = choice.message
    if getattr(message, "refusal", None):
        raise ValueError("模型拒绝生成")
    text = str(getattr(message, "content", "") or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for position, character in enumerate(text):
            if character != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(text[position:])
                break
            except json.JSONDecodeError:
                continue
        else:
            raise ValueError("模型未返回 JSON 对象") from None
    if not isinstance(payload, dict):
        raise ValueError("模型返回值不是 JSON 对象")
    return payload
