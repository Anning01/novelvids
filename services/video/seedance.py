"""Seedance/即梦 视频生成器。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from services.video.base import BaseVideoGenerator
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)


class SeedanceGenerator(BaseVideoGenerator):
    """Seedance/即梦 平台视频生成。

    Submit: POST {base_url}/videos/generations
    Query:  GET  {base_url}/videos/generations/{task_id}
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
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": self.config.model,
            "negative_prompt": negative_prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
        }
        if subjects:
            payload["subjects"] = subjects

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.config.base_url}/videos/generations",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        task_id = data.get("task_id") or data.get("id")
        logger.info("Seedance submit: task_id=%s", task_id)
        return task_id

    async def query(self, external_task_id: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url}/videos/generations/{external_task_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status", "")
        progress = data.get("progress", 0)

        if status in ("completed", "success"):
            video_url = data.get("url") or data.get("video_url")
            return self._build_result(
                TaskStatusEnum.completed, progress=100, url=video_url,
            )

        if status == "failed":
            return self._build_result(
                TaskStatusEnum.failed,
                error=data.get("error"),
            )

        return self._build_result(TaskStatusEnum.running, progress=progress)
