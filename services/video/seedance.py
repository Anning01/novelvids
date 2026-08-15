"""Seedance/即梦 视频生成器。"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.video.base import BaseVideoGenerator, VideoProviderError
from services.video.capabilities import capabilities_for
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)

# 匹配 @{Name} 和 @Name（兼容旧格式）
_ENTITY_RE = re.compile(r"@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)")


class SeedanceGenerationError(VideoProviderError):
    """脱敏后可安全返回给调用方的 Seedance 接口错误。"""


def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def _request_id(response: httpx.Response) -> str | None:
    for name in ("x-request-id", "request-id", "x-volc-request-id"):
        if value := response.headers.get(name):
            return value[:120]
    return None


def _provider_error(data: Any) -> str | None:
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


def _http_provider_error(response: httpx.Response) -> str | None:
    """只提取结构化供应商错误，避免把 HTML 或请求内容原样暴露给调用方。"""
    try:
        return _provider_error(response.json())
    except ValueError:
        return None


def _video_url(data: Any) -> str | None:
    """兼容查询接口中字符串或对象形式的 video_url。"""
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
        return _video_url(content)
    if isinstance(content, list):
        for item in content:
            if url := _video_url(item):
                return url
    return None


def _last_frame_url(data: Any) -> str | None:
    """兼容查询接口中顶层、content 及对象形式的尾帧地址。"""
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
        return _last_frame_url(content)
    if isinstance(content, list):
        for item in content:
            if url := _last_frame_url(item):
                return url
    return None


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
        if not subjects:
            # 没有 subjects，清理掉所有 @引用
            return _ENTITY_RE.sub(lambda m: m.group(1) or m.group(2), prompt), []

        # 按名称索引 subjects
        subj_map: dict[str, dict[str, Any]] = {s["name"]: s for s in subjects}

        # 收集参考图，限制总数，并建立 name -> 图片序号 的映射
        ref_images: list[str] = []
        name_to_index: dict[str, int] = {}

        for subj in subjects:
            if len(ref_images) >= max_ref_images:
                break
            images = subj.get("images", [])
            if images:
                name_to_index[subj["name"]] = len(ref_images) + 1  # 1-based
                remaining = max_ref_images - len(ref_images)
                ref_images.extend(images[:remaining])

        # 替换 prompt 中的 @引用
        def _replace(m: re.Match) -> str:
            name = m.group(1) or m.group(2)
            subj = subj_map.get(name)
            if not subj:
                return name
            idx = name_to_index.get(subj["name"])
            if idx is not None:
                return f"[图{idx}]"
            # 超出图片限额，用描述替代
            return subj.get("description") or subj["name"]

        processed = _ENTITY_RE.sub(_replace, prompt)
        return processed, ref_images

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
        extra_reference_images = list(dict.fromkeys(kwargs.get("reference_images") or []))
        reference_videos = list(dict.fromkeys(kwargs.get("reference_videos") or []))
        capabilities = capabilities_for(self.config.video_model_type)

        # 首尾帧模式只使用两张关键帧；参考图模式继续解析 @资产。
        processed_prompt, ref_images = self._process_prompt(
            prompt,
            subjects if generation_mode == "reference" else None,
            capabilities.max_reference_images,
        )
        logger.info(
            "seedance_prompt_prepared subjects=%d reference_images=%d prompt_length=%d",
            len(subjects or []), len(ref_images), len(processed_prompt),
        )

        # 构建 content 数组（官方格式）
        content: list[dict[str, Any]] = [
            {"type": "text", "text": processed_prompt}
        ]
        if generation_mode == "keyframes":
            content.extend([
                {"type": "image_url", "image_url": {"url": first_frame_url}, "role": "first_frame"},
                {"type": "image_url", "image_url": {"url": last_frame_url}, "role": "last_frame"},
            ])
        else:
            for img in ref_images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img},
                    "role": "reference_image",
                })
            for img in extra_reference_images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img},
                    "role": "reference_image",
                })
            for video in reference_videos:
                content.append({
                    "type": "video_url",
                    "video_url": {"url": video},
                    "role": "reference_video",
                })

        payload: dict[str, Any] = {
            "model": self.config.model,
            "content": content,
            "duration": int(duration),
            "resolution": resolution,
            "ratio": aspect_ratio,
            "generate_audio": generate_audio,
            "return_last_frame": return_last_frame,
            "watermark": False,
        }
        if "mov" in capabilities.output_formats:
            payload["output_format"] = output_format

        url = f"{self.config.base_url.rstrip('/')}/contents/generations/tasks"
        safe_url = _safe_endpoint(url)
        logger.info(
            "seedance_outbound endpoint=%s model=%s mode=%s images=%d videos=%d duration=%s "
            "resolution=%s ratio=%s format=%s audio=%s return_last_frame=%s",
            safe_url,
            self.config.model,
            generation_mode,
            len(ref_images) + len(extra_reference_images),
            len(reference_videos),
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
        logger.info("Seedance submit: task_id=%s, images=%d", task_id, len(ref_images))
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
