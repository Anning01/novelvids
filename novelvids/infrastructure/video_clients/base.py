"""Base class for video generation clients."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class VideoTaskStatus(str, Enum):
    """Video generation task status."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class VideoTask:
    """Video generation task result."""

    task_id: str
    status: VideoTaskStatus
    progress: int = 0
    video_url: str | None = None
    thumbnail_url: str | None = None
    error: str | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class ReferenceImage:
    """Reference image for video generation."""

    id: str
    image_data: str  # Base64 encoded image data
    label: str = ""


class VideoClient(ABC):
    """Abstract base class for video generation API clients."""

    @abstractmethod
    async def create_video(
        self,
        prompt: str,
        reference_images: list[ReferenceImage],
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        negative_prompt: str | None = None,
    ) -> VideoTask:
        """
        Create a video generation task.

        Args:
            prompt: Text prompt for video generation
            reference_images: List of reference images
            duration: Video duration in seconds
            aspect_ratio: Video aspect ratio
            negative_prompt: Negative prompt to avoid certain elements

        Returns:
            VideoTask with task_id for polling
        """
        pass

    @abstractmethod
    async def get_task_status(self, task_id: str) -> VideoTask:
        """
        Get the status of a video generation task.

        Args:
            task_id: The task ID from create_video

        Returns:
            VideoTask with current status and video_url if completed
        """
        pass

    @abstractmethod
    def build_prompt_with_refs(
        self, prompt: str, reference_images: list[ReferenceImage]
    ) -> str:
        """
        Build prompt with platform-specific reference image markers.

        The prompt may contain {ref:id} placeholders that need to be
        replaced with platform-specific markers like @id (Vidu) or [图N] (Doubao).

        Args:
            prompt: Prompt with {ref:id} placeholders
            reference_images: List of reference images

        Returns:
            Prompt with platform-specific markers
        """
        pass

    async def close(self) -> None:
        """Close any resources (e.g., HTTP client sessions)."""
        pass
