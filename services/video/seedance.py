"""Seedance/即梦 视频生成器。"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from services.video.base import BaseVideoGenerator
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)

# 匹配 @{Name} 和 @Name（兼容旧格式）
_ENTITY_RE = re.compile(r"@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)")

MAX_REF_IMAGES = 4


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
            if len(ref_images) >= MAX_REF_IMAGES:
                break
            images = subj.get("images", [])
            if images:
                # 取该资产的第一张图（主图）
                ref_images.append(images[0])
                name_to_index[subj["name"]] = len(ref_images)  # 1-based

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

        # 处理 prompt 和参考图
        processed_prompt, ref_images = self._process_prompt(prompt, subjects)
        logger.info(
            "Seedance _process_prompt: subjects=%d, ref_images=%d, prompt[:80]=%r",
            len(subjects or []), len(ref_images), processed_prompt[:80],
        )

        # 自动切换 t2v / i2v 模型
        model_name = self.config.model
        supports_images = "i2v" in model_name or "t2v" in model_name
        if ref_images and "t2v" in model_name:
            model_name = model_name.replace("t2v", "i2v")
            logger.info("Seedance auto-switch: t2v -> i2v (has images)")
        elif not ref_images and "i2v" in model_name:
            model_name = model_name.replace("i2v", "t2v")
            logger.info("Seedance auto-switch: i2v -> t2v (no images)")
        elif ref_images and not supports_images:
            # 模型名中无 t2v/i2v，不支持参考图，丢弃图片避免 r2v 错误
            logger.warning(
                "Seedance model %s does not support reference images, skipping %d images",
                model_name, len(ref_images),
            )
            ref_images = []

        # 构建 content 数组（官方格式）
        content: list[dict[str, Any]] = [
            {"type": "text", "text": processed_prompt}
        ]
        for img in ref_images:
            content.append({
                "type": "image_url",
                "image_url": {"url": img},
                "role": "reference_image",
            })

        payload: dict[str, Any] = {
            "model": model_name,
            "content": content,
            "duration": int(duration),
            "watermark": False,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            url = f"{self.config.base_url}/contents/generations/tasks"
            logger.info("Seedance request: POST %s\npayload: %s", url, {
                **payload,
                "content": [
                    {**c, "image_url": {"url": c["image_url"]["url"][:80] + "..."}} if c.get("image_url") else c
                    for c in payload["content"]
                ],
            })
            resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code != 200:
                logger.error("Seedance error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            data = resp.json()

        task_id = data.get("id")
        logger.info("Seedance submit: task_id=%s, images=%d", task_id, len(ref_images))
        return task_id

    async def query(self, external_task_id: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url}/contents/generations/tasks/{external_task_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status", "")
        logger.info("Seedance query: task=%s, status=%s, keys=%s", external_task_id, status, list(data.keys()))

        if status in ("succeeded", "completed", "success"):
            # 打印完整响应结构（截断长字段）
            logger.info("Seedance succeeded response: %s", {
                k: (str(v)[:200] + "..." if isinstance(v, (str, list)) and len(str(v)) > 200 else v)
                for k, v in data.items()
            })
            # 从 content 提取视频地址（content 可能是 dict 或 list）
            video_url = None
            resp_content = data.get("content")
            if isinstance(resp_content, dict):
                video_url = resp_content.get("video_url") or resp_content.get("url")
            elif isinstance(resp_content, list):
                for item in resp_content:
                    if isinstance(item, dict):
                        video_url = item.get("video_url") or item.get("url")
                        if video_url:
                            break
            # 备选字段
            if not video_url:
                video_url = data.get("video_url") or data.get("url")
            logger.info("Seedance video_url: %s", video_url)
            return self._build_result(
                TaskStatusEnum.completed, progress=100, url=video_url,
            )

        if status == "failed":
            error_msg = data.get("error", {})
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            # 翻译常见错误为中文
            if isinstance(error_msg, str) and "sensitive" in error_msg.lower():
                error_msg = "生成的视频可能包含敏感内容，请修改提示词后重试"
            return self._build_result(
                TaskStatusEnum.failed,
                error=error_msg,
            )

        return self._build_result(TaskStatusEnum.running)
