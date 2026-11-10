"""Generic asynchronous /v1/videos protocol, independent of the configured host."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, ValidationError

from services.video.base import BaseVideoGenerator, VideoProviderError
from services.video.capabilities import capabilities_for, validate_selection
from services.video.content import PreparedVideoContent, prepare_video_content, reference_indexes, replace_display_mentions
from services.video.provider_http import public_provider_error, request_id
from services.video.public_media import PublicMediaResolver, public_media_url
from utils.enums import TaskStatusEnum
from utils.messages import localized_message


logger = logging.getLogger(__name__)


class VideoOutput(BaseModel):
    url: str | None = None


class VideoTask(BaseModel):
    id: str = Field(min_length=1)
    status: Literal["queued", "in_progress", "completed", "failed"]
    progress: int = Field(default=0, ge=0, le=100)
    metadata: VideoOutput | None = None


def _endpoint(base_url: str, task_id: str | None = None) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1/videos"):
        url = root
    elif root.endswith("/v1"):
        url = f"{root}/videos"
    else:
        url = f"{root}/v1/videos"
    return f"{url}/{quote(task_id, safe='')}" if task_id is not None else url


def _prompt(prepared: PreparedVideoContent, reference_images: list[str], reference_videos: list[str], video_names: list[str]) -> str:
    rendered = prepared.prompt
    for label, kind, urls in (("图片", "image", reference_images), ("视频", "video", reference_videos)):
        if kind == "video" and video_names:
            bindings = {f"【参考视频：{name}】": f"@video{index}" for name, index in
                zip(video_names, reference_indexes(prepared, "reference_video", urls))}
            rendered = re.sub(r"【参考视频：[^】]+】", lambda match: bindings.get(match[0], match[0]), rendered)
            continue
        rendered = replace_display_mentions(rendered, mention_label=label, reference_label=f"@{kind}",
            indexes=reference_indexes(prepared, f"reference_{kind}", urls))
    labels = {"图片": "image", "图": "image", "视频": "video", "音频": "audio"}
    return re.sub(r"\[(图片|图|视频|音频)(\d+)]|@(?:\{)?(图片|图|视频|音频)(\d+)(?:})?",
        lambda match: f"@{labels[match[1] or match[3]]}{match[2] or match[4]}", rendered)


class UnifiedVideoGenerator(BaseVideoGenerator):
    """Translate shared video inputs without exposing service-specific details."""

    async def _request(self, method: str, task_id: str | None = None, payload: dict | None = None) -> dict:
        submitting = method == "POST"
        async with httpx.AsyncClient(timeout=600) as client:
            try:
                response = await client.request(method, _endpoint(self.config.base_url, task_id),
                    headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
                    **({"json": payload} if payload is not None else {}))
            except httpx.HTTPError as exc:
                not_sent = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
                logger.warning("video_api_network_error operation=%s error_type=%s", method, type(exc).__name__)
                raise VideoProviderError(localized_message('视频接口网络请求失败'),
                    submission_uncertain=submitting and not not_sent) from None
        logger.info("video_api_response operation=%s status=%s request_id=%s", method, response.status_code, request_id(response) or "-")
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code >= 400:
            raise VideoProviderError(public_provider_error(data, status_code=response.status_code,
                transport_request_id=request_id(response), secrets=(self.config.api_key,)),
                submission_uncertain=submitting and (response.status_code >= 500 or response.status_code == 408))
        if not isinstance(data, dict):
            raise VideoProviderError(localized_message('视频接口返回了无效响应'), submission_uncertain=submitting)
        if data.get("error"):
            data = {**data, "error": public_provider_error(data, status_code=response.status_code,
                transport_request_id=request_id(response), secrets=(self.config.api_key,))}
        return data

    async def submit(self, prompt: str, negative_prompt: str = "", subjects: list[dict[str, Any]] | None = None,
        duration: float = 6.0, aspect_ratio: str = "16:9", **kwargs) -> str:
        mode = kwargs.get("generation_mode", "reference")
        selection = validate_selection(self.config.video_model_type, api_protocol=self.config.api_protocol,
            generation_mode=mode, resolution=kwargs.get("resolution"), aspect_ratio=aspect_ratio,
            duration=duration, output_format=kwargs.get("output_format"), generate_audio=kwargs.get("generate_audio"),
            return_last_frame=kwargs.get("return_last_frame"))
        caps = capabilities_for(self.config.video_model_type, self.config.api_protocol)
        images = kwargs.get("reference_images") or []
        videos = kwargs.get("reference_videos") or []
        prepared = prepare_video_content(prompt=prompt, subjects=subjects, generation_mode=mode,
            max_reference_images=caps.max_reference_images, first_frame_url=kwargs.get("first_frame_url"),
            last_frame_url=kwargs.get("last_frame_url"), reference_images=images,
            reference_videos=videos, reference_audios=kwargs.get("reference_audios") or [])
        resolver = PublicMediaResolver(team_id=kwargs.get("team_id", self.config.team_id))
        references = []
        for item in prepared.items[1:]:
            kind = item["type"].removesuffix("_url")
            references.append({"type": kind,
                "role": item["role"] if item["role"] in {"first_frame", "last_frame"} else "reference",
                "url": await resolver.resolve(item[item["type"]]["url"])})
        payload = {"model": self.config.model, "prompt": _prompt(prepared, images, videos, kwargs.get("reference_video_names") or []),
            "duration": selection.duration, "aspect_ratio": selection.aspect_ratio,
            "resolution": selection.resolution, "watermark": False}
        if references:
            payload["references"] = references
        logger.info("video_api_submit images=%d videos=%d audios=%d duration=%d resolution=%s",
            prepared.reference_image_count, prepared.reference_video_count, prepared.reference_audio_count,
            selection.duration, selection.resolution)
        data = await self._request("POST", payload=payload)
        if data.get("error"):
            raise VideoProviderError(data["error"])
        task_id = data.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise VideoProviderError(localized_message('视频接口未返回任务 ID'), submission_uncertain=True)
        return task_id.strip()

    async def query(self, external_task_id: str) -> dict[str, Any]:
        data = await self._request("GET", task_id=external_task_id)
        try:
            task = VideoTask.model_validate(data)
        except ValidationError:
            raise VideoProviderError(localized_message('视频接口返回了无效任务状态')) from None
        if task.status == "completed":
            if not task.metadata or not task.metadata.url:
                raise VideoProviderError(localized_message('视频任务已完成但未返回成片地址'))
            url = public_media_url(task.metadata.url)
            return self._build_result(TaskStatusEnum.completed, progress=100, url=url)
        if task.status == "failed":
            message = data.get("error") or localized_message('视频生成失败，请检查生成内容或联系管理员')
            return self._build_result(TaskStatusEnum.failed, error=message)
        status = TaskStatusEnum.queued if task.status == "queued" else TaskStatusEnum.running
        return self._build_result(status, progress=task.progress)
