"""视频生成器基类和公共工具函数。"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from models.config import AiModelConfig
from utils.enums import TaskStatusEnum


# MIME 类型映射
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def image_to_base64(image_path: str) -> str:
    """将本地图片转为 base64 data URI。"""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    mime_type = MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
    base64_str = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime_type};base64,{base64_str}"


class BaseVideoGenerator(ABC):
    """视频生成器抽象基类。

    所有平台 (Vidu, Veo, Sora, Seedance) 实现此接口。
    """

    def __init__(self, config: AiModelConfig):
        self.config = config

    @abstractmethod
    async def submit(
        self,
        prompt: str,
        negative_prompt: str = "",
        subjects: list[dict[str, Any]] | None = None,
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        **kwargs,
    ) -> str:
        """提交视频生成请求。

        Returns:
            外部平台返回的 task_id。
        """

    @abstractmethod
    async def query(self, external_task_id: str) -> dict[str, Any]:
        """查询视频生成进度。

        Returns:
            dict with keys: status (TaskStatusEnum), progress (int|None),
            url (str|None), metadata (dict).
        """

    # ------ 辅助方法 ------

    def _build_result(
        self,
        status: TaskStatusEnum,
        progress: int | None = None,
        url: str | None = None,
        **extra,
    ) -> dict[str, Any]:
        """统一构建 query 返回值。"""
        return {
            "status": status,
            "progress": progress,
            "url": url,
            "metadata": extra,
        }
