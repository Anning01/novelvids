"""Seedance/即梦 视频生成器。"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from services.video.base import BaseVideoGenerator, VideoProviderError
from services.video.capabilities import capabilities_for
from services.video.content import prepare_video_content, process_subject_prompt
from services.video.provider_http import (
    http_provider_error as _http_provider_error,
    last_frame_url as _last_frame_url,
    provider_error as _provider_error,
    request_id as _request_id,
    safe_endpoint as _safe_endpoint,
    video_url as _video_url,
)
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)

class SeedanceGenerationError(VideoProviderError):
    """脱敏后可安全返回给调用方的 Seedance 接口错误。"""


class SeedanceGenerator(BaseVideoGenerator):
    """Seedance/即梦 平台视频生成。

    Submit: POST {base_url}/contents/generations/tasks
    Query:  GET  {base_url}/contents/generations/tasks/{task_id}
    Auth:   Bearer {api_key}
    """

    # ------ prompt 处理 ------

    @staticmethod
    def _process_prompt(
        prompt: str,
        subjects: list[dict[str, Any]] | None,
        max_ref_images: int = 30,
    ) -> tuple[str, list[str]]:
        """处理 prompt 中的 @资产引用，返回 (处理后的 prompt, 参考图列表)。

        规则:
        - 收集所有资产的参考图，上限 MAX_REF_IMAGES 张
        - 有参考图的资产: @{Name} -> [Name]
        - 无参考图 / 超出上限的资产: @{Name} -> 资产描述文本
        """
        return process_subject_prompt(prompt, subjects, max_ref_images)

    # ------ API 调用 ------

    async def submit(
        self,
        prompt: str,
        negative_prompt: str = "",
        subjects: list[dict[str, Any]] | None = None,
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        **kwargs,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        generation_mode = kwargs.get("generation_mode", "reference")
        first_frame_url = kwargs.get("first_frame_url")
        last_frame_url = kwargs.get("last_frame_url")
        resolution = str(kwargs.get("resolution") or "720p")
        output_format = str(kwargs.get("output_format") or "mp4")
        generate_audio = bool(kwargs.get("generate_audio", True))
        return_last_frame = bool(kwargs.get("return_last_frame", False))
        capabilities = capabilities_for(self.config.video_model_type)

        prepared = prepare_video_content(
            prompt=prompt,
            subjects=subjects,
            generation_mode=generation_mode,
            max_reference_images=capabilities.max_reference_images,
            first_frame_url=first_frame_url,
            last_frame_url=last_frame_url,
            reference_images=kwargs.get("reference_images") or [],
            reference_videos=kwargs.get("reference_videos") or [],
            reference_audios=kwargs.get("reference_audios") or [],
        )
        logger.info(
            "seedance_prompt_prepared subjects=%d reference_images=%d reference_audios=%d prompt_length=%d",
            len(subjects or []), prepared.reference_image_count, prepared.reference_audio_count, len(prepared.prompt),
        )

        payload: dict[str, Any] = {
            "model": self.config.model,
            "content": prepared.items,
            "duration": int(duration),
            "resolution": resolution,
            "ratio": aspect_ratio,
            "generate_audio": generate_audio,
            "return_last_frame": return_last_frame,
            "watermark": False,
        }
        if "mov" in capabilities.output_formats:
            payload["output_format"] = output_format
        if (
            capabilities.max_request_size_mb is not None
            and len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            > capabilities.max_request_size_mb * 1024 * 1024
        ):
            raise SeedanceGenerationError(
                f"Seedance 请求体不能超过 {capabilities.max_request_size_mb}MB，请将大文件上传 OSS 后使用公网 URL"
            )

        url = f"{self.config.base_url.rstrip('/')}/contents/generations/tasks"
        safe_url = _safe_endpoint(url)
        logger.info(
            "seedance_outbound endpoint=%s model=%s mode=%s images=%d videos=%d audios=%d duration=%s "
            "resolution=%s ratio=%s format=%s audio=%s return_last_frame=%s",
            safe_url,
            self.config.model,
            generation_mode,
            prepared.reference_image_count,
            prepared.reference_video_count,
            prepared.reference_audio_count,
            payload["duration"],
            resolution,
            aspect_ratio,
            output_format,
            generate_audio,
            return_last_frame,
        )
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                logger.warning(
                    "seedance_network_error endpoint=%s error_type=%s",
                    safe_url,
                    type(exc).__name__,
                )
                raise SeedanceGenerationError("视频供应商网络请求失败") from exc

        request_id = _request_id(resp)
        if resp.status_code >= 400:
            provider_error = _http_provider_error(resp)
            logger.warning(
                "seedance_http_error endpoint=%s status=%s request_id=%s has_provider_detail=%s",
                safe_url,
                resp.status_code,
                request_id or "-",
                bool(provider_error),
            )
            suffix = f"，request_id={request_id}" if request_id else ""
            if provider_error:
                raise SeedanceGenerationError(
                    f"视频供应商请求失败：{provider_error}（HTTP {resp.status_code}{suffix}）"
                )
            raise SeedanceGenerationError(f"视频供应商请求失败（HTTP {resp.status_code}{suffix}）")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SeedanceGenerationError("视频供应商返回了无法解析的响应") from exc
        if error := _provider_error(data):
            suffix = f"，request_id={request_id}" if request_id else ""
            raise SeedanceGenerationError(f"视频供应商返回错误：{error}{suffix}")

        task_id = data.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise SeedanceGenerationError("视频供应商未返回任务 ID")
        logger.info("Seedance submit: task_id=%s, images=%d", task_id, prepared.reference_image_count)
        return task_id.strip()

    async def query(self, external_task_id: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url.rstrip('/')}/contents/generations/tasks/{external_task_id}"

        safe_url = _safe_endpoint(url)
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning(
                    "seedance_query_network_error endpoint=%s error_type=%s",
                    safe_url,
                    type(exc).__name__,
                )
                raise SeedanceGenerationError("查询视频任务时网络请求失败") from exc
        request_id = _request_id(resp)
        if resp.status_code >= 400:
            provider_error = _http_provider_error(resp)
            suffix = f"，request_id={request_id}" if request_id else ""
            if provider_error:
                raise SeedanceGenerationError(
                    f"查询视频任务失败：{provider_error}（HTTP {resp.status_code}{suffix}）"
                )
            raise SeedanceGenerationError(f"查询视频任务失败（HTTP {resp.status_code}{suffix}）")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SeedanceGenerationError("视频供应商返回了无法解析的任务状态") from exc

        status = data.get("status", "")
        logger.info("Seedance query: task=%s, status=%s, keys=%s", external_task_id, status, list(data.keys()))

        if status in ("succeeded", "completed", "success"):
            video_url = _video_url(data)
            metadata = {
                "duration": data.get("duration"),
                "frames": data.get("frames"),
            }
            if last_frame_url := _last_frame_url(data):
                metadata["last_frame_url"] = last_frame_url
            logger.info(
                "seedance_query_completed task=%s has_video_url=%s request_id=%s",
                external_task_id,
                bool(video_url),
                request_id or "-",
            )
            return self._build_result(
                TaskStatusEnum.completed,
                progress=100,
                url=video_url,
                **metadata,
            )

        if status in ("failed", "expired", "cancelled", "canceled"):
            error_msg = _provider_error(data) or "视频生成任务失败"
            # 翻译常见错误为中文
            if isinstance(error_msg, str) and "sensitive" in error_msg.lower():
                error_msg = "生成的视频可能包含敏感内容，请修改提示词后重试"
            return self._build_result(
                TaskStatusEnum.failed,
                error=error_msg,
            )

        if status == "queued":
            return self._build_result(TaskStatusEnum.queued)
        return self._build_result(TaskStatusEnum.running)
