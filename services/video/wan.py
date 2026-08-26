"""Alibaba Model Studio Wan 3.0 asynchronous video adapter."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from services.video.base import BaseVideoGenerator, VideoProviderError
from services.video.capabilities import capabilities_for
from services.video.content import PreparedVideoContent, prepare_video_content
from services.video.dashscope_upload import DashScopeTemporaryFileUploader
from services.video.provider_http import (
    http_provider_error,
    last_frame_url as provider_last_frame_url,
    provider_error,
    request_id,
    safe_endpoint,
    video_url,
)
from utils.enums import TaskStatusEnum


logger = logging.getLogger(__name__)


class Wan3GenerationError(VideoProviderError):
    """Sanitized Wan 3 provider error safe for persistence and UI display."""


_SUBMIT_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"
_TASKS_PATH = "/api/v1/tasks"
_MEDIA_TYPE_BY_ROLE = {
    "first_frame": "first_frame",
    "last_frame": "last_frame",
    "reference_image": "reference_image",
    "reference_video": "reference_video",
    "reference_audio": "reference_audio",
}


def _wan_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    for marker in (_SUBMIT_PATH, _TASKS_PATH):
        if marker in root:
            root = root.split(marker, 1)[0]
    return root.rstrip("/")


def _wan_endpoint(base_url: str, operation: str, task_id: str | None = None) -> str:
    root = _wan_root(base_url)
    if operation == "submit":
        return f"{root}{_SUBMIT_PATH}"
    if operation == "query" and task_id:
        return f"{root}{_TASKS_PATH}/{quote(task_id, safe='')}"
    raise ValueError(f"Unsupported Wan operation: {operation}")


def _reference_indexes(
    prepared: PreparedVideoContent,
    role: str,
    source_urls: list[str],
) -> list[int]:
    """Map controller display mentions back to their Wan per-media-type indexes."""
    ordered_urls: list[str] = []
    for item in prepared.items:
        if item.get("role") != role:
            continue
        item_type = str(item.get("type") or "")
        value = item.get(item_type)
        url = value.get("url") if isinstance(value, dict) else None
        if isinstance(url, str):
            ordered_urls.append(url)
    return [ordered_urls.index(url) + 1 for url in source_urls if url in ordered_urls]


def _replace_display_mentions(
    prompt: str,
    *,
    mention_label: str,
    reference_label: str,
    indexes: list[int],
) -> str:
    iterator = iter(indexes)

    def replace(match: re.Match[str]) -> str:
        index = next(iterator, None)
        return f"{reference_label}{index}" if index is not None else match.group(0)

    return re.sub(rf"【参考{mention_label}：[^】]+】", replace, prompt)


def _wan_prompt(
    prompt: str,
    *,
    image_indexes: list[int],
    video_indexes: list[int],
) -> str:
    """Translate shared factory references to Wan's documented 图/视频/音频 syntax."""
    rendered = _replace_display_mentions(
        prompt,
        mention_label="图片",
        reference_label="图",
        indexes=image_indexes,
    )
    rendered = _replace_display_mentions(
        rendered,
        mention_label="视频",
        reference_label="视频",
        indexes=video_indexes,
    )
    rendered = re.sub(r"\[(图|视频|音频)(\d+)]", r"\1\2", rendered)
    return re.sub(r"@(?:图片|图|视频|音频)(\d+)", lambda match: (
        f"图{match.group(1)}" if match.group(0).startswith(("@图", "@图片")) else match.group(0)[1:]
    ), rendered)


def _wan_media(prepared: PreparedVideoContent) -> list[dict[str, str]]:
    media: list[dict[str, str]] = []
    for item in prepared.items:
        role = str(item.get("role") or "")
        media_type = _MEDIA_TYPE_BY_ROLE.get(role)
        if media_type is None:
            continue
        item_type = str(item.get("type") or "")
        value = item.get(item_type)
        url = value.get("url") if isinstance(value, dict) else None
        if isinstance(url, str) and url.strip():
            media.append({"type": media_type, "url": url.strip()})
    return media


async def _resolve_wan_media(
    media: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
) -> list[dict[str, str]]:
    uploader = DashScopeTemporaryFileUploader(api_key=api_key, model=model)
    resolved: list[dict[str, str]] = []
    for item in media:
        resolved.append({**item, "url": await uploader.resolve(item["url"])})
    return resolved


class Wan3Generator(BaseVideoGenerator):
    """Wan 3.0 All-in-One video generation through DashScope async tasks."""

    async def submit(
        self,
        prompt: str,
        negative_prompt: str = "",
        subjects: list[dict[str, Any]] | None = None,
        duration: float = 5.0,
        aspect_ratio: str = "adaptive",
        **kwargs,
    ) -> str:
        del negative_prompt
        if len(prompt) > 20_000:
            raise Wan3GenerationError("Wan 3 视频提示词不能超过 20000 个字符")
        generation_mode = str(kwargs.get("generation_mode") or "reference")
        capabilities = capabilities_for(self.config.video_model_type)
        prepared = prepare_video_content(
            prompt=prompt,
            subjects=subjects,
            generation_mode=generation_mode,
            max_reference_images=capabilities.max_reference_images,
            first_frame_url=kwargs.get("first_frame_url"),
            last_frame_url=kwargs.get("last_frame_url"),
            reference_images=kwargs.get("reference_images") or [],
            reference_videos=kwargs.get("reference_videos") or [],
            reference_audios=kwargs.get("reference_audios") or [],
        )
        media = await _resolve_wan_media(
            _wan_media(prepared),
            api_key=self.config.api_key,
            model=self.config.model,
        )
        input_payload: dict[str, Any] = {
            "prompt": _wan_prompt(
                prepared.prompt,
                image_indexes=_reference_indexes(
                    prepared,
                    "reference_image",
                    list(kwargs.get("reference_images") or []),
                ),
                video_indexes=_reference_indexes(
                    prepared,
                    "reference_video",
                    list(kwargs.get("reference_videos") or []),
                ),
            )
        }
        if media:
            input_payload["media"] = media
        payload = {
            "model": self.config.model,
            "input": input_payload,
            "parameters": {
                "resolution": str(kwargs.get("resolution") or capabilities.default_resolution),
                "ratio": aspect_ratio or capabilities.default_aspect_ratio,
                "duration": int(duration),
                "audio": bool(kwargs.get("generate_audio", True)),
                "prompt_extend": True,
                "watermark": False,
            },
        }
        url = _wan_endpoint(self.config.base_url, "submit")
        safe_url = safe_endpoint(url)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        if any(item["url"].startswith("oss://") for item in media):
            headers["X-DashScope-OssResourceResolve"] = "enable"
        logger.info(
            "wan3_outbound endpoint=%s model=%s mode=%s images=%d videos=%d audios=%d duration=%s resolution=%s ratio=%s",
            safe_url,
            self.config.model,
            generation_mode,
            prepared.reference_image_count,
            prepared.reference_video_count,
            prepared.reference_audio_count,
            payload["parameters"]["duration"],
            payload["parameters"]["resolution"],
            payload["parameters"]["ratio"],
        )
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                logger.warning("wan3_network_error endpoint=%s error_type=%s", safe_url, type(exc).__name__)
                raise Wan3GenerationError("Wan 3 视频供应商网络请求失败") from exc
        response_request_id = request_id(response)
        if response.status_code >= 400:
            detail = http_provider_error(response)
            suffix = f"，request_id={response_request_id}" if response_request_id else ""
            if detail:
                raise Wan3GenerationError(
                    f"Wan 3 视频请求失败：{detail}（HTTP {response.status_code}{suffix}）"
                )
            raise Wan3GenerationError(f"Wan 3 视频请求失败（HTTP {response.status_code}{suffix}）")
        try:
            data = response.json()
        except ValueError as exc:
            raise Wan3GenerationError("Wan 3 返回了无法解析的响应") from exc
        if error := provider_error(data):
            raise Wan3GenerationError(f"Wan 3 返回错误：{error}")
        output = data.get("output")
        task_id = output.get("task_id") if isinstance(output, dict) else None
        if not isinstance(task_id, str) or not task_id.strip():
            raise Wan3GenerationError("Wan 3 未返回任务 ID")
        return task_id.strip()

    async def query(self, external_task_id: str) -> dict[str, Any]:
        url = _wan_endpoint(self.config.base_url, "query", external_task_id)
        safe_url = safe_endpoint(url)
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("wan3_query_network_error endpoint=%s error_type=%s", safe_url, type(exc).__name__)
                raise Wan3GenerationError("查询 Wan 3 视频任务时网络请求失败") from exc
        response_request_id = request_id(response)
        if response.status_code >= 400:
            detail = http_provider_error(response)
            suffix = f"，request_id={response_request_id}" if response_request_id else ""
            if detail:
                raise Wan3GenerationError(
                    f"查询 Wan 3 视频任务失败：{detail}（HTTP {response.status_code}{suffix}）"
                )
            raise Wan3GenerationError(f"查询 Wan 3 视频任务失败（HTTP {response.status_code}{suffix}）")
        try:
            data = response.json()
        except ValueError as exc:
            raise Wan3GenerationError("Wan 3 返回了无法解析的任务状态") from exc
        output = data.get("output")
        if not isinstance(output, dict):
            raise Wan3GenerationError("Wan 3 任务响应缺少 output 数据")
        status = str(output.get("task_status") or "").upper()
        logger.info(
            "wan3_query task=%s status=%s request_id=%s",
            external_task_id,
            status,
            response_request_id or data.get("request_id") or "-",
        )
        if status == "SUCCEEDED":
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            metadata: dict[str, Any] = {
                "usage": usage,
                "duration": usage.get("output_video_duration", usage.get("duration")),
                "resolution": usage.get("SR"),
                "ratio": usage.get("ratio"),
                "fps": usage.get("fps"),
            }
            if last_frame_url := provider_last_frame_url(output):
                metadata["last_frame_url"] = last_frame_url
            return self._build_result(
                TaskStatusEnum.completed,
                progress=100,
                url=video_url(output),
                **metadata,
            )
        if status == "FAILED":
            return self._build_result(
                TaskStatusEnum.failed,
                error=provider_error(output) or "Wan 3 视频生成任务失败",
            )
        if status == "CANCELED":
            return self._build_result(
                TaskStatusEnum.cancelled,
                error=provider_error(output) or "Wan 3 视频生成任务已取消",
            )
        if status == "UNKNOWN":
            return self._build_result(
                TaskStatusEnum.failed,
                error="Wan 3 任务不存在或已超过 24 小时有效期",
            )
        if status == "PENDING":
            return self._build_result(TaskStatusEnum.queued)
        if status == "RUNNING":
            return self._build_result(TaskStatusEnum.running)
        raise Wan3GenerationError(f"Wan 3 返回未知任务状态：{status or 'empty'}")
