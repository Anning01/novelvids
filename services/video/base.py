"""视频生成器基类和公共工具函数。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from models.config import AiModelConfig
from services.image_inputs import image_to_base64
from utils.enums import TaskStatusEnum


class VideoProviderError(RuntimeError):
    """视频供应商边界错误；调用方可安全持久化其脱敏后的消息。"""


class BaseVideoGenerator(ABC):
    """视频生成器抽象基类；当前开放的后台能力由 Seedance 实现。"""

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
