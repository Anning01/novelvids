"""Doubao (豆包) video generation API client - Volcano Engine."""

import httpx
from loguru import logger

from .base import ReferenceImage, VideoClient, VideoTask, VideoTaskStatus


class DoubaoClient(VideoClient):
    """Client for Doubao/Volcano Engine video generation API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "doubao-seedance-1-0-lite-i2v-250428",
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-initialize HTTP client."""
        if self._client is None:
            logger.info(f"[Doubao] Base URL: {self.base_url}")
            logger.info(f"[Doubao] Timeout: {self.timeout}s")
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
                trust_env=False,  # Bypass system proxy to avoid connection issues with large payloads
            )
        return self._client

    def build_prompt_with_refs(
        self, prompt: str, reference_images: list[ReferenceImage]
    ) -> str:
        """
        Replace {ref:id} placeholders with [图N] markers.

        Doubao uses [图N] format to reference images in prompts.
        Example: "{ref:xiaoyu} stands on the bridge" -> "[图1] stands on the bridge"
        """
        result = prompt
        for idx, ref in enumerate(reference_images, start=1):
            placeholder = f"{{ref:{ref.id}}}"
            marker = f"[图{idx}]"
            result = result.replace(placeholder, marker)
        return result

    async def create_video(
        self,
        prompt: str,
        reference_images: list[ReferenceImage],
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        negative_prompt: str | None = None,
    ) -> VideoTask:
        """Create a video generation task with Doubao API."""
        # Build prompt with [图N] markers
        final_prompt = self.build_prompt_with_refs(prompt, reference_images)

        # Truncate to 2000 characters
        if len(final_prompt) > 2000:
            logger.warning(f"[Doubao] Prompt truncated from {len(final_prompt)} to 2000 chars")
            final_prompt = final_prompt[:1997] + "..."

        # Build content array (text + images)
        content = [{"type": "text", "text": final_prompt}]

        for ref in reference_images:
            image_data_len = len(ref.image_data)
            logger.debug(f"[Doubao] Reference image: id={ref.id}, image_data_len={image_data_len}")
            content.append({
                "type": "image_url",
                "image_url": {"url": ref.image_data},  # Can be base64 or URL
                "role": "reference_image",
            })

        # Map aspect ratio format
        ratio_map = {"16:9": "16:9", "9:16": "9:16", "1:1": "1:1", "21:9": "21:9"}
        ratio = ratio_map.get(aspect_ratio, "16:9")

        payload = {
            "model": self.model,
            "content": content,
            "ratio": ratio,
            "duration": min(int(duration), 5),  # Doubao max is 5s
            "watermark": False,
            "resolution": "720p",
        }

        # Log full request details (without full image data)
        log_content = [{"type": c["type"], "text_len": len(c.get("text", "")) if c["type"] == "text" else None, "image_data_len": len(c.get("image_url", {}).get("url", "")) if c["type"] == "image_url" else None} for c in content]
        logger.info(f"[Doubao] Request: model={self.model}, prompt_len={len(final_prompt)}, images_count={len(reference_images)}, duration={payload['duration']}, ratio={ratio}")
        logger.debug(f"[Doubao] Prompt: {final_prompt[:500]}...")
        logger.debug(f"[Doubao] Content structure: {log_content}")

        try:
            response = await self.client.post("/content_generation/tasks", json=payload)
            logger.info(f"[Doubao] Response status: {response.status_code}")
            
            response.raise_for_status()
            data = response.json()
            logger.debug(f"[Doubao] Response data: {data}")

            task_id = data.get("id")
            if not task_id:
                logger.error(f"[Doubao] No task id in response: {data}")
                return VideoTask(
                    task_id="",
                    status=VideoTaskStatus.FAILED,
                    error="No task id in response",
                    raw_response=data,
                )

            logger.info(f"[Doubao] Task created successfully: task_id={task_id}")
            return VideoTask(
                task_id=task_id,
                status=VideoTaskStatus.PENDING,
                raw_response=data,
            )

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            logger.error(f"[Doubao] API error: status={e.response.status_code}, body={error_body}")
            return VideoTask(
                task_id="",
                status=VideoTaskStatus.FAILED,
                error=f"HTTP {e.response.status_code}: {error_body}",
            )
        except Exception as e:
            logger.exception(f"[Doubao] Client error: {e}")
            return VideoTask(
                task_id="",
                status=VideoTaskStatus.FAILED,
                error=str(e),
            )

    async def get_task_status(self, task_id: str) -> VideoTask:
        """Poll Doubao task status and get video URL when complete."""
        try:
            response = await self.client.get(f"/content_generation/tasks/{task_id}")
            response.raise_for_status()
            data = response.json()

            status = data.get("status", "")

            if status == "running" or status == "pending":
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.PROCESSING,
                    progress=50,  # Doubao doesn't provide progress %
                    raw_response=data,
                )
            elif status == "succeeded":
                content = data.get("content", {})
                video_url = content.get("video_url")
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.SUCCEEDED,
                    progress=100,
                    video_url=video_url,
                    raw_response=data,
                )
            elif status == "failed":
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.FAILED,
                    error=data.get("error", "Unknown error"),
                    raw_response=data,
                )
            else:
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.PENDING,
                    raw_response=data,
                )

        except Exception as e:
            logger.error(f"Doubao status check error: {e}")
            return VideoTask(
                task_id=task_id,
                status=VideoTaskStatus.FAILED,
                error=str(e),
            )

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
