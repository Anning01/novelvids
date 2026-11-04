"""AutoDL ComfyUI 异步视频接口；下载与轮询调度复用现有视频流程。"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from services.video.base import BaseVideoGenerator, VideoProviderError
from services.video.capabilities import capabilities_for, validate_selection
from services.video.content import prepare_video_content
from services.video.provider_http import safe_endpoint
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)


class AutoDLGenerationError(VideoProviderError):
    """可安全持久化的渠道错误，不回显供应商正文。"""


def _workflow_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith('/comfyui_workflow'):
        return root
    if root.endswith('/api/v1/comfyui'):
        return f'{root}/comfyui_workflow'
    return f'{root}/api/v1/comfyui/comfyui_workflow'


class AutoDLVideoGenerator(BaseVideoGenerator):
    async def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        headers = {"Authorization": self.config.api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(method, url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise AutoDLGenerationError("AutoDL 视频接口网络请求失败") from exc
        # 仅记录结构与状态，Token、提示词、参考素材和结果签名 URL 均不入日志。
        logger.info("autodl_response endpoint=%s http_status=%s", safe_endpoint(url), response.status_code)
        if response.status_code >= 400:
            raise AutoDLGenerationError(f"AutoDL 视频请求失败（HTTP {response.status_code}）")
        try:
            body = response.json()
        except ValueError as exc:
            raise AutoDLGenerationError("AutoDL 返回了无法解析的响应") from exc
        if not isinstance(body, dict) or body.get("code") != "Success":
            raise AutoDLGenerationError("AutoDL 视频接口返回错误，请在渠道后台检查任务")
        data = body.get("data")
        if not isinstance(data, dict):
            raise AutoDLGenerationError("AutoDL 响应缺少任务数据")
        return data

    async def submit(
        self, prompt: str, negative_prompt: str = "",
        subjects: list[dict[str, Any]] | None = None,
        duration: float = 6.0, aspect_ratio: str = "16:9", **kwargs,
    ) -> str:
        if not prompt.strip() or len(prompt) > 20000:
            raise AutoDLGenerationError("AutoDL 视频提示词必须为 1–20000 个字符")
        capabilities = capabilities_for(self.config.video_model_type)
        selection = validate_selection(
            self.config.video_model_type,
            generation_mode=kwargs.get("generation_mode") or "reference",
            resolution=kwargs.get("resolution"), aspect_ratio=aspect_ratio,
            duration=duration, output_format=kwargs.get("output_format"),
            generate_audio=kwargs.get("generate_audio"),
            return_last_frame=kwargs.get("return_last_frame"),
        )
        if kwargs.get("reference_videos") or kwargs.get("first_frame_url") or kwargs.get("last_frame_url"):
            raise AutoDLGenerationError("AutoDL 当前工作流不支持参考视频或首尾帧")
        prepared = prepare_video_content(
            prompt=prompt, subjects=subjects, generation_mode="reference",
            max_reference_images=capabilities.max_reference_images,
            reference_images=kwargs.get("reference_images"),
            reference_audios=kwargs.get("reference_audios"),
        )
        if prepared.reference_image_count > capabilities.max_reference_images or prepared.reference_audio_count > capabilities.max_reference_audios:
            raise AutoDLGenerationError("AutoDL 当前工作流最多支持 9 张参考图和 3 段音频")
        ratio_suffix = {"16:9": "横", "9:16": "竖", "1:1": "(1:1)"}
        payload = {
            "prompt": prepared.prompt, "duration": selection.duration,
            "resolution": selection.resolution + ratio_suffix[selection.aspect_ratio],
        }
        for kind, field in (("image", "ref_image"), ("audio", "ref_audio")):
            urls = [item[f"{kind}_url"]["url"] for item in prepared.items if item["type"] == f"{kind}_url"]
            for index, url in enumerate(urls):
                if urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
                    raise AutoDLGenerationError("AutoDL 参考素材需要可访问的 HTTP(S) URL")
                payload[f"{field}_{index}"] = url
        # 与已跑通示例一致：无图时使用工作流的空白图。
        payload.setdefault("ref_image_0", "https://codewithgpu.ks3-cn-beijing.ksyuncs.com/comfyui_api/blank/blank.png")
        url = f"{_workflow_endpoint(self.config.base_url)}/{quote(self.config.model, safe='')}"
        logger.info(
            "autodl_submit endpoint=%s images=%d audios=%d duration=%s resolution=%s",
            safe_endpoint(url), prepared.reference_image_count, prepared.reference_audio_count,
            selection.duration, payload["resolution"],
        )
        data = await self._request("POST", url, payload)
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise AutoDLGenerationError("AutoDL 未返回任务 ID")
        return task_id.strip()

    async def query(self, external_task_id: str) -> dict[str, Any]:
        url = f"{_workflow_endpoint(self.config.base_url)}/result/{quote(external_task_id, safe='')}"
        data = await self._request("GET", url)
        status = str(data.get("status") or "").upper()
        if status in {"SUCCESS", "COMPLETED"}:
            results = data.get("results")
            if isinstance(results, list):
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") != "video" and item.get("file_type") != "mp4":
                        continue
                    video_url = item.get("url")
                    if isinstance(video_url, str) and urlsplit(video_url).scheme in {"http", "https"} and urlsplit(video_url).hostname:
                        # data.duration 是推理耗时，不能覆盖请求中的成片时长。
                        return self._build_result(TaskStatusEnum.completed, progress=100, url=video_url)
            raise AutoDLGenerationError("AutoDL 任务成功但未返回视频 URL")
        if status in {"FAILED", "ERROR"}:
            return self._build_result(TaskStatusEnum.failed, error="AutoDL 视频生成任务失败，请在渠道后台检查任务")
        if status in {"CANCELLED", "CANCELED"}:
            return self._build_result(TaskStatusEnum.cancelled)
        if status == "QUEUED":
            return self._build_result(TaskStatusEnum.queued)
        if status == "RUNNING":
            return self._build_result(TaskStatusEnum.running)
        raise AutoDLGenerationError("AutoDL 返回未知任务状态")
