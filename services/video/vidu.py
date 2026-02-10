"""Vidu (ViduQ2) 视频生成器。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from services.video.base import BaseVideoGenerator
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)


class ViduGenerator(BaseVideoGenerator):
    """Vidu 平台视频生成。

    Submit: POST {base_url}/reference2video
    Query:  GET  {base_url}/tasks/{task_id}/creations
    Auth:   Token {api_key}
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
            "Authorization": f"Token {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": self.config.model,
            "negative_prompt": negative_prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "audio": True,
            "is_rec": True,
            "bgm": False,
        }
        if subjects:
            payload["subjects"] = subjects

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.config.base_url}/reference2video",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        task_id = data.get("task_id") or data.get("id")
        logger.info("Vidu submit: task_id=%s", task_id)
        return task_id

    async def query(self, external_task_id: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Token {self.config.api_key}",
            "Content-Type": "application/json",
        }
        # base_url 形如 https://api.vidu.cn/ent/v2
        # 查询端点: /tasks/{task_id}/creations
        url = f"{self.config.base_url}/tasks/{external_task_id}/creations"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        state = data.get("state", "")
        progress = data.get("progress", 0)

        if state == "success":
            creations = data.get("creations", [])
            video_url = creations[0].get("url") if creations else None
            return self._build_result(
                TaskStatusEnum.completed, progress=100, url=video_url,
                creations=creations,
            )

        if state == "failed":
            return self._build_result(
                TaskStatusEnum.failed,
                err_code=data.get("err_code"),
            )

        # processing / queueing
        return self._build_result(TaskStatusEnum.running, progress=progress)
