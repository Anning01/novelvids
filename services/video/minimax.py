"""MiniMax H3 视频生成适配器。"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

from services.video.base import BaseVideoGenerator, VideoProviderError
from services.video.capabilities import capabilities_for
from services.video.content import prepare_video_content
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


class MiniMaxGenerationError(VideoProviderError):
    """脱敏后可安全返回给调用方的 MiniMax 接口错误。"""


def _minimax_endpoint(base_url: str, operation: str, task_id: str | None = None) -> str:
    """兼容填写 API 根地址、/v2 或完整创建端点。"""
    root = base_url.rstrip("/")
    for suffix in ("/v2/query/video_generation", "/v2/video_generation"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
            break
    if root.endswith("/v2"):
        root = root[:-3]
    if operation == "submit":
        return f"{root}/v2/video_generation"
    if operation == "query" and task_id:
        return f"{root}/v2/query/video_generation/{quote(task_id, safe='')}"
    raise ValueError(f"Unsupported MiniMax operation: {operation}")


def _resolution(value: str) -> str:
    normalized = value.strip().lower()
    return {"768p": "768P", "2k": "2K"}.get(normalized, value)


class MiniMaxH3Generator(BaseVideoGenerator):
    """MiniMax H3 官方异步视频接口。

    Submit: POST {base_url}/v2/video_generation
    Query:  GET  {base_url}/v2/query/video_generation/{task_id}
    Auth:   Bearer {api_key}
    """

    async def submit(
        self,
        prompt: str,
        negative_prompt: str = "",
        subjects: list[dict[str, Any]] | None = None,
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        **kwargs,
    ) -> str:
        del negative_prompt  # H3 v2 接口没有独立 negative_prompt 字段。
        if not prompt.strip():
            raise MiniMaxGenerationError("MiniMax H3 视频提示词不能为空")
        if len(prompt) > 7000:
            raise MiniMaxGenerationError("MiniMax H3 视频提示词不能超过 7000 个字符")
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

        # 官方约束：首尾帧模式只能使用 adaptive；纯文本模式不能使用 adaptive。
        ratio = "adaptive" if generation_mode == "keyframes" else aspect_ratio
        has_reference_media = bool(
            prepared.reference_image_count or prepared.reference_video_count
        )
        if generation_mode == "reference" and not has_reference_media and ratio == "adaptive":
            ratio = capabilities.default_aspect_ratio

        payload: dict[str, Any] = {
            "model": self.config.model,
            "content": prepared.items,
            "resolution": _resolution(
                str(kwargs.get("resolution") or capabilities.default_resolution)
            ),
            "duration": int(duration),
            "ratio": ratio,
            "aigc_watermark": False,
        }
        if (
            capabilities.max_request_size_mb is not None
            and len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            > capabilities.max_request_size_mb * 1024 * 1024
        ):
            raise MiniMaxGenerationError(
                f"MiniMax H3 请求体不能超过 {capabilities.max_request_size_mb}MB，请将大文件改用公网 URL"
            )
        url = _minimax_endpoint(self.config.base_url, "submit")
        safe_url = safe_endpoint(url)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        logger.info(
            "minimax_h3_outbound endpoint=%s model=%s mode=%s images=%d videos=%d audios=%d "
            "duration=%s resolution=%s ratio=%s",
            safe_url,
            self.config.model,
            generation_mode,
            prepared.reference_image_count,
            prepared.reference_video_count,
            prepared.reference_audio_count,
            payload["duration"],
            payload["resolution"],
            payload["ratio"],
        )
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                logger.warning(
                    "minimax_h3_network_error endpoint=%s error_type=%s",
                    safe_url,
                    type(exc).__name__,
                )
                raise MiniMaxGenerationError("MiniMax 视频供应商网络请求失败") from exc

        response_request_id = request_id(response)
        if response.status_code >= 400:
            detail = http_provider_error(response)
            suffix = f"，request_id={response_request_id}" if response_request_id else ""
            if detail:
                raise MiniMaxGenerationError(
                    f"MiniMax 视频请求失败：{detail}（HTTP {response.status_code}{suffix}）"
                )
            raise MiniMaxGenerationError(
                f"MiniMax 视频请求失败（HTTP {response.status_code}{suffix}）"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise MiniMaxGenerationError("MiniMax 返回了无法解析的响应") from exc
        if error := provider_error(data):
            raise MiniMaxGenerationError(f"MiniMax 返回错误：{error}")
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise MiniMaxGenerationError("MiniMax 未返回任务 ID")
        return task_id.strip()

    async def query(self, external_task_id: str) -> dict[str, Any]:
        url = _minimax_endpoint(self.config.base_url, "query", external_task_id)
        safe_url = safe_endpoint(url)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning(
                    "minimax_h3_query_network_error endpoint=%s error_type=%s",
                    safe_url,
                    type(exc).__name__,
                )
                raise MiniMaxGenerationError("查询 MiniMax 视频任务时网络请求失败") from exc

        response_request_id = request_id(response)
        if response.status_code >= 400:
            detail = http_provider_error(response)
            suffix = f"，request_id={response_request_id}" if response_request_id else ""
            if detail:
                raise MiniMaxGenerationError(
                    f"查询 MiniMax 视频任务失败：{detail}（HTTP {response.status_code}{suffix}）"
                )
            raise MiniMaxGenerationError(
                f"查询 MiniMax 视频任务失败（HTTP {response.status_code}{suffix}）"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise MiniMaxGenerationError("MiniMax 返回了无法解析的任务状态") from exc

        task = data.get("task")
        if not isinstance(task, dict):
            raise MiniMaxGenerationError("MiniMax 任务响应缺少 task 数据")
        status = str(task.get("status") or "").lower()
        logger.info(
            "minimax_h3_query task=%s status=%s request_id=%s",
            external_task_id,
            status,
            response_request_id or "-",
        )
        if status == "succeeded":
            metadata = {
                key: task.get(key)
                for key in ("duration", "resolution", "ratio", "usage", "task_type", "modality")
                if task.get(key) is not None
            }
            if last_frame_url := provider_last_frame_url(task):
                metadata["last_frame_url"] = last_frame_url
            return self._build_result(
                TaskStatusEnum.completed,
                progress=100,
                url=video_url(task),
                **metadata,
            )
        if status == "failed":
            return self._build_result(
                TaskStatusEnum.failed,
                error=provider_error(task) or "MiniMax 视频生成任务失败",
            )
        if status == "cancelled":
            return self._build_result(
                TaskStatusEnum.cancelled,
                error=provider_error(task) or "MiniMax 视频生成任务已取消",
            )
        if status == "queued":
            return self._build_result(TaskStatusEnum.queued)
        if status == "running":
            return self._build_result(TaskStatusEnum.running)
        raise MiniMaxGenerationError(f"MiniMax 返回未知任务状态：{status or 'empty'}")
