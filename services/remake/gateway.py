"""重制工坊多模态视频理解模型边界。"""

from __future__ import annotations

from utils.messages import localized_message

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

from services.llm.usage import completion_usage

MAX_MODEL_VIDEO_BYTES = 35_000_000
VIDEO_INPUT_FPS = 1.0
ANALYSIS_TIMEOUT_SECONDS = 600.0
ANALYSIS_ERROR_CODE = "REMAKE_VIDEO_ANALYSIS_FAILED"

logger = logging.getLogger(__name__)


class RemakeVideoAnalysisError(RuntimeError):
    """包含供应商/接口真实错误信息，且安全脱敏的模型错误。"""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = ANALYSIS_ERROR_CODE,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.error_code = error_code
        self.user_message = message
        if error_code == ANALYSIS_ERROR_CODE or "（错误代码：" in message:
            display_message = localized_message(message)
        else:
            display_message = localized_message("{p0}（错误代码：{p1}）", p0=localized_message(message), p1=error_code)
        super().__init__(display_message)
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
        context_builder: Callable[[int], str | dict[str, Any]] | None = None,
        on_completed: Callable[[int, int], Awaitable[None]] | None = None,
        completed_results: dict[int, dict] | None = None,
        held_shots: frozenset[int] = frozenset(),
        continuity_language: str | None = None,
        block_size: int = 0,
        draft_results: dict | None = None,
        audit_results: dict | None = None,
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(max(1, int(self.config.concurrency or 1)))
        completion_lock = asyncio.Lock()
        failure: Exception | None = None
        saved = completed_results or {}
        completed = len(saved)
        if completed and on_completed:
            await on_completed(completed, len(paths))

        async def analyze(index: int, path: Path, previous=None) -> dict[str, Any]:
            nonlocal completed, failure
            if index in saved:
                return {**saved[index], "shot_index": index, "file": path.name}
            async with semaphore:
                if failure is not None:
                    raise failure
                try:
                    context = context_builder(index) if context_builder else ""
                    if previous is not None:
                        from prompts.remake import shot_continuity
                        context = {**(context if isinstance(context, dict) else {"references": context}),
                                   **shot_continuity(previous, index - 1, continuity_language)}
                    result = await self.analyze_one(
                        index=index,
                        path=path,
                        prompt=prompt,
                        context=context,
                        schema_name=schema_name,
                        response_schema=response_schema,
                    )
                except Exception as error:
                    if failure is None:
                        failure = error
                    raise
            if on_completed is not None:
                async with completion_lock:
                    completed += 1
                    await on_completed(completed, len(paths))
            return result

        if continuity_language and block_size > 1 and len(paths) > block_size and (self.config.concurrency > 1 or draft_results) and not held_shots:
            from services.remake.shot_blocks import confirmed_blocks
            from services.creation_agent.skill_execution import current_execution
            from services.creation_agent.operation_receipts import execute_step
            from prompts.remake import shot_continuity

            async def generate(i, prev, draft):
                context = context_builder(i) if context_builder else {}
                if prev is not None:
                    context = {**(context if isinstance(context, dict) else {"references": context}),
                               **shot_continuity(prev, i - 1, continuity_language)}
                return await self.analyze_one(index=i, path=paths[i - 1], prompt=prompt, schema_name=schema_name,
                    response_schema=response_schema, context=context, draft=draft)

            async def promote(i, data):
                execution = current_execution.get()
                async def validated():
                    return data
                if execution:
                    return await execute_step(execution.params["task_id"], f"model:remake:RemakeShot:{i}", validated, atomic=True)
                return data

            async def audit(i, previous, candidate):
                from schemas.remake import RemakeContinuityVerdict
                from prompts.remake import continuity_audit_facts, continuity_audit_instruction
                kept = (audit_results or {}).get(i)
                if kept is None:
                    context = context_builder(i) if context_builder else {}
                    facts = continuity_audit_facts(i, previous, candidate, context, continuity_language)
                    kept = await self.analyze_one(index=i, path=paths[i - 1],
                        prompt=continuity_audit_instruction(continuity_language), schema_name="shot_continuity_check",
                        response_schema=RemakeContinuityVerdict.model_json_schema(), context=facts)
                return RemakeContinuityVerdict.model_validate({k: kept[k] for k in ("consistent", "reason")}).consistent

            execution = current_execution.get()
            shared_window = execution and execution.params.get("remake_context_version", 0) >= 2
            result = await confirmed_blocks(len(paths), block_size, capacity=None if shared_window else self.config.concurrency,
                language=continuity_language, confirmed=dict(saved), drafts=dict(draft_results or {}),
                run=generate, promote=promote, report=on_completed, audit=audit)
            return [{**value, "shot_index": i, "file": paths[i - 1].name} for i, value in enumerate(result, 1)]

        if continuity_language is not None:
            confirmed = []
            for index, path in enumerate(paths, 1):
                if index in held_shots:
                    break
                confirmed.append(await analyze(index, path, confirmed[-1] if confirmed else None))
            return confirmed

        # Let accepted calls finish and checkpoint before releasing their clip files.
        results = await asyncio.gather(*(analyze(i, path) for i, path in enumerate(paths, 1) if i not in held_shots), return_exceptions=True)
        if failure is not None:
            raise failure
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return list(results)

    async def analyze_one(
        self,
        *,
        index: int,
        path: Path,
        prompt: str,
        schema_name: str,
        response_schema: dict[str, Any],
        context: str | dict[str, Any] = "",
        include_segment_metadata: bool = True,
        draft: bool = False,
    ) -> dict[str, Any]:
        from contextlib import nullcontext
        from services.creation_agent.skill_execution import current_execution
        from services.remake.analysis_capacity import provider_pressure, window_for
        execution = current_execution.get()
        gate = nullcontext()
        window = None
        if execution and getattr(execution, "params", {}).get("remake_context_version", 0) >= 2:
            from models.agent_operation import AgentOperation
            model_key = getattr(self.config, "id", None) or self.config.model
            window = window_for(model_key)
            segment = f"draft-{index}" if draft else index

            async def announce(state):
                await AgentOperation.update_or_create(task_id=execution.params["task_id"],
                    key=f"capacity:remake:{segment}", defaults={"state": state})

            gate = window.admit(max(1, int(self.config.concurrency or 1)), draft=draft,
                                notify=announce if schema_name == "professional_video_prompt_material" else None)
        async with gate:
            try:
                return await self._request_one(index=index, path=path, prompt=prompt, schema_name=schema_name,
                    response_schema=response_schema, context=context, include_segment_metadata=include_segment_metadata, draft=draft)
            except RemakeVideoAnalysisError as exc:
                if window and provider_pressure(exc):
                    await window.slow_down(15)
                raise

    async def _request_one(self, *, index, path, prompt, schema_name, response_schema, context, include_segment_metadata, draft):
        started_at = self.clock()
        from prompts.remake import render_remake_request
        from utils.prompt_language import task_language
        from services.creation_agent.skill_execution import current_execution
        execution = current_execution.get()
        if execution:
            from pydantic_ai import BinaryContent, VideoUrl
            from schemas.agent_workflow import RemakeAssets, RemakeShot
            from schemas.remake import RemakeContinuityVerdict, RemakeSpeechEvidence
            audit = schema_name in {'shot_continuity_check', 'shot_speech_evidence'}
            schema = {"shot_continuity_check": RemakeContinuityVerdict, "shot_speech_evidence": RemakeSpeechEvidence,
                      "global_key_assets": RemakeAssets}.get(schema_name, RemakeShot)
            if getattr(self.config, "api_protocol", None) == "novelvids":
                mime = self._video_mime(path)
                url = await self._platform_video_url(path, execution.params.get("team_id"))
                video_content = VideoUrl(url=url, media_type=mime, vendor_metadata={"fps": VIDEO_INPUT_FPS})
            else:
                video_bytes, mime = await asyncio.to_thread(self._read_video, path)
                video_content = BinaryContent(data=video_bytes, media_type=mime, vendor_metadata={"fps": VIDEO_INPUT_FPS})
            from services.model_concurrency import capacity_observer
            from models.agent_operation import AgentOperation
            receipt_segment = f"draft-{index}" if draft else index
            async def capacity_state(state):
                await AgentOperation.update_or_create(task_id=execution.params["task_id"],
                    key=f"capacity:remake:{receipt_segment}", defaults={"state": state})
            async def validate_shot(output):
                from services.remake.storyboards import prepare_remake_prompt
                prepare_remake_prompt(output.model_dump(), context["assets"], execution.snapshot, execution.language,
                                      strategy_key=context["storyboard_strategy"], duration_seconds=context["duration_seconds"])

            from prompts.remake import continuity_instruction, identity_instruction
            extra = prompt if audit else ""
            context_version = getattr(execution, 'params', {}).get('remake_context_version', 0)
            if context_version >= 2 and not audit:
                extra = identity_instruction(execution.language) if schema is RemakeAssets else continuity_instruction(execution.language)
            observer = capacity_observer.set(capacity_state if schema is RemakeShot and context_version else None)
            try:
                result = await execution.generate(
                    'structured' if audit else 'remake',
                    context if audit else {'segment': index, 'assets': context, 'output_kind': schema_name},
                    schema,
                    model_config=self.config,
                    media=[video_content],
                    **({"additional_instructions": extra} if extra else {}),
                    **({"receipt_segment": f"draft-{index}"} if draft else {}),
                    **({"output_validator": validate_shot} if schema is RemakeShot and context_version else {}),
                )
            except Exception as error:
                from services.remake.output_recovery import recover_shot_output
                if schema is RemakeShot:
                    recovered = await recover_shot_output(execution.params["task_id"], receipt_segment)
                    if recovered is not None and context_version:
                        try:
                            await validate_shot(recovered)
                        except ValueError:
                            recovered = None
                    if recovered is not None:
                        data = recovered.model_dump(mode="json")
                        await AgentOperation.filter(task_id=execution.params["task_id"],
                            key=f"model:remake:RemakeShot:{receipt_segment}").update(state="completed", result=data)
                        if include_segment_metadata:
                            data.update(shot_index=index, file=path.name)
                        return data
                self._record_timing(index=index, schema_name=schema_name, started_at=started_at, attempts=1, status='failed', draft=draft)
                _log_provider_failure(error, model=str(self.config.model), schema_name=schema_name, attempt=1)
                message, error_code = _provider_failure(error, index=index)
                raise RemakeVideoAnalysisError(message, error_code=error_code, usage=dict(self.usage)) from None
            finally:
                capacity_observer.reset(observer)
            data = result.model_dump()
            if include_segment_metadata:
                data.update(shot_index=index, file=path.name)
            self._record_timing(index=index, schema_name=schema_name, started_at=started_at, attempts=1, status='completed', draft=draft)
            return data
        if getattr(self.config, "api_protocol", None) == "novelvids":
            self._video_mime(path)
            url = await self._platform_video_url(path, None)
            video_input = {"type": "video_url", "video_url": {"url": url, "fps": VIDEO_INPUT_FPS}}
        else:
            video_input = await asyncio.to_thread(self._build_video_input, path)
        instruction = render_remake_request(prompt, context=context, index=index,
            schema=response_schema, include_segment_metadata=include_segment_metadata, language=task_language.get() or "zh")
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
        from utils.model_reasoning import reasoning_parameters
        options = reasoning_parameters(getattr(self.config, 'thinking', None), getattr(self.config, 'reasoning_effort', None))
        if options:
            request['extra_body'] = options
        from utils.model_limits import DEFAULT_OUTPUT_TOKENS
        output_limit = getattr(self.config, "max_tokens", None)
        request["max_tokens"] = output_limit if output_limit is not None else DEFAULT_OUTPUT_TOKENS

        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            try:
                from services.model_concurrency import model_slots
                async with model_slots.hold(getattr(self.config, 'id', None)):
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
                    status="completed", draft=draft,
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
                        status="failed", draft=draft,
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
        raise RemakeVideoAnalysisError(localized_message('视频片段分析未完成'), usage=dict(self.usage))

    def _record_timing(
        self,
        *,
        index: int,
        schema_name: str,
        started_at: float,
        attempts: int,
        status: str,
        draft: bool = False,
    ) -> None:
        duration_ms = max(0, round((self.clock() - started_at) * 1000))
        timing = {
            "index": index,
            "schema_name": schema_name,
            "duration_ms": duration_ms,
            "attempts": attempts,
            "status": status,
        }
        if draft:
            timing["draft"] = True
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

    def _video_mime(self, path: Path) -> str:
        if not path.is_file():
            raise RemakeVideoAnalysisError(
                localized_message('模型输入视频不存在'),
                error_code="REMAKE_ANALYSIS_MEDIA_MISSING",
            )
        raw_size = path.stat().st_size
        if raw_size > MAX_MODEL_VIDEO_BYTES:
            raise RemakeVideoAnalysisError(
                localized_message('模型输入视频超过 {p1} 字节上限', p1=f'{MAX_MODEL_VIDEO_BYTES}'),
                error_code="REMAKE_ANALYSIS_MEDIA_TOO_LARGE",
            )
        return "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"

    def _read_video(self, path: Path) -> tuple[bytes, str]:
        mime = self._video_mime(path)
        return path.read_bytes(), mime

    async def _platform_video_url(self, path: Path, team_id: int | None) -> str:
        from services.oss.studio_client import studio_client
        client = studio_client(team_id, base_url=self.config.base_url, api_key=self.config.api_key)
        if client is None:
            raise RemakeVideoAnalysisError(localized_message("本地猫影的平台密钥尚未配置"))
        return await client.resolve(path)

    def _build_video_input(self, path: Path) -> dict[str, Any]:
        data, mime = self._read_video(path)
        encoded = base64.b64encode(data).decode("ascii")
        return {
            "type": "video_url",
            "video_url": {
                "url": f"data:{mime};base64,{encoded}",
                "fps": VIDEO_INPUT_FPS,
            },
        }

    def _add_usage(self, usage: dict[str, int]) -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cache_read_tokens"):
            if key in usage:
                self.usage[key] = self.usage.get(key, 0) + int(usage[key] or 0)


def _is_retryable(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        return True
    return status_code in {408, 409, 429} or status_code >= 500


def _extract_error_detail(error: Exception) -> str:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        nested = body.get("error")
        if isinstance(nested, dict) and nested.get("message"):
            return str(nested["message"]).strip()
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
        if body.get("message"):
            return str(body["message"]).strip()
        if body.get("detail"):
            return str(body["detail"]).strip()
    msg = getattr(error, "message", None)
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    from pydantic import ValidationError
    from pydantic_ai.exceptions import UnexpectedModelBehavior
    if isinstance(error, (ValidationError, UnexpectedModelBehavior)):
        lines = [line.strip() for line in str(error).splitlines() if line.strip() and not line.startswith("For further information")]
        if lines:
            return "；".join(lines[:3])
    text = str(error).strip()
    if text:
        return text
    return type(error).__name__


def _sanitize_error_detail(detail: str) -> str:
    if not detail:
        return ""
    detail = re.sub(r"(?:ark|sk)-[a-zA-Z0-9_\-]{8,}", "***", detail)
    detail = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]{8,}", "Bearer ***", detail, flags=re.IGNORECASE)
    detail = re.sub(r"secret-[^\s]+", "***", detail, flags=re.IGNORECASE)
    return detail.strip()


def _provider_failure(error: Exception, *, index: int) -> tuple[str, str]:
    status_code = getattr(error, "status_code", None)
    if status_code == 400:
        return localized_message('视频分析请求与当前模型能力不兼容'), "REMAKE_ANALYSIS_REQUEST_INVALID"
    if status_code in {401, 403}:
        return localized_message('视频分析模型鉴权失败，请检查 API Key、访问白名单及模型权限'), "REMAKE_ANALYSIS_AUTH_FAILED"
    if status_code == 404:
        return localized_message('视频分析模型不存在或不可用'), "REMAKE_ANALYSIS_MODEL_NOT_FOUND"
    if status_code == 429:
        return localized_message('视频分析模型请求过于频繁，请稍后重试'), "REMAKE_ANALYSIS_RATE_LIMITED"
    if isinstance(status_code, int) and status_code >= 500:
        return localized_message('视频分析服务暂时不可用'), "REMAKE_ANALYSIS_PROVIDER_UNAVAILABLE"
    error_type = type(error).__name__.lower()
    if "connection" in error_type or "timeout" in error_type:
        return localized_message('无法连接视频分析服务'), "REMAKE_ANALYSIS_CONNECTION_FAILED"

    raw_detail = _extract_error_detail(error)
    detail = _sanitize_error_detail(raw_detail)
    if detail:
        return localized_message("第 {p0} 个视频片段分析失败：{p1}", p0=index, p1=detail), ANALYSIS_ERROR_CODE
    return localized_message("第 {p0} 个视频片段分析失败", p0=index), ANALYSIS_ERROR_CODE


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
        raise ValueError(localized_message('模型输出被截断'))
    message = choice.message
    if getattr(message, "refusal", None):
        raise ValueError(localized_message('模型拒绝生成'))
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
            raise ValueError(localized_message('模型未返回 JSON 对象')) from None
    if not isinstance(payload, dict):
        raise ValueError(localized_message('模型返回值不是 JSON 对象'))
    return payload
