"""Vidu video generation API client."""

import aiohttp
from loguru import logger

from .base import ReferenceImage, VideoClient, VideoTask, VideoTaskStatus


class ViduClient(VideoClient):
    """Client for Vidu video generation API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.vidu.cn/ent/v2",
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    def build_prompt_with_refs(
        self, prompt: str, reference_images: list[ReferenceImage]
    ) -> str:
        """
        Replace {ref:id} placeholders with @id markers.

        Vidu uses @id format to reference subjects in prompts.
        Supports both canonical_name and UUID placeholders for backwards compatibility.
        Example: "{ref:xiaoyu} stands on the bridge" -> "@xiaoyu stands on the bridge"
        """
        result = prompt
        for ref in reference_images:
            # Replace canonical_name placeholder
            placeholder = f"{{ref:{ref.id}}}"
            marker = f"@{ref.id}"
            result = result.replace(placeholder, marker)

            # Also replace by label if different (for backwards compatibility)
            if ref.label and ref.label != ref.id:
                placeholder_label = f"{{ref:{ref.label}}}"
                result = result.replace(placeholder_label, marker)
        return result

    async def create_video(
        self,
        prompt: str,
        reference_images: list[ReferenceImage],
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        negative_prompt: str | None = None,
    ) -> VideoTask:
        """Create a video generation task with Vidu API."""
        # Build prompt with @id markers
        final_prompt = self.build_prompt_with_refs(prompt, reference_images)

        # Truncate to 2000 characters
        if len(final_prompt) > 2000:
            logger.warning(f"[Vidu] Prompt truncated from {len(final_prompt)} to 2000 chars")
            final_prompt = final_prompt[:1997] + "..."

        # Build subjects array
        subjects = []
        for ref in reference_images:
            image_data_len = len(ref.image_data)
            logger.debug(f"[Vidu] Subject: id={ref.id}, image_data_len={image_data_len}")
            subjects.append({"id": ref.id, "images": [ref.image_data]})

        payload = {
            "prompt": final_prompt,
            "model": "viduq2",
            "duration": min(duration, 8.0),  # Vidu max is 8s
            "aspect_ratio": aspect_ratio,
            "subjects": subjects,
            "audio": True,
            "is_rec": True,
            "bgm": False,
            "off_peak": False,
        }

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/reference2video"

        # Log request details (without full image data)
        log_payload = {
            **payload,
            "subjects": [
                {"id": s["id"], "images_count": len(s["images"]), "image_data_len": len(s["images"][0]) if s["images"] else 0}
                for s in subjects
            ]
        }
        logger.info(f"[Vidu] Request: url={url}, prompt_len={len(final_prompt)}, subjects_count={len(subjects)}, duration={payload['duration']}, aspect_ratio={payload['aspect_ratio']}")
        logger.debug(f"[Vidu] Prompt: {final_prompt[:500]}...")
        logger.debug(f"[Vidu] Full payload (without image data): {log_payload}")

        # Create connector
        connector = aiohttp.TCPConnector()

        try:
            async with aiohttp.ClientSession(connector=connector, timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    status = resp.status
                    text = await resp.text()
                    logger.info(f"[Vidu] Response status: {status}")
                    logger.info(f"[Vidu] Response body: {text[:500]}...")

                    if status != 200:
                        logger.error(f"[Vidu] API error: status={status}, body={text}")
                        return VideoTask(
                            task_id="",
                            status=VideoTaskStatus.FAILED,
                            error=f"HTTP {status}: {text[:200]}",
                        )

                    data = await resp.json()

            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                logger.error(f"[Vidu] No task_id in response: {data}")
                return VideoTask(
                    task_id="",
                    status=VideoTaskStatus.FAILED,
                    error="No task_id in response",
                    raw_response=data,
                )

            logger.info(f"[Vidu] Task created successfully: task_id={task_id}")
            return VideoTask(
                task_id=task_id,
                status=VideoTaskStatus.PENDING,
                raw_response=data,
            )

        except aiohttp.ClientSSLError as e:
            logger.error(f"[Vidu] SSL error: {e}")
            return VideoTask(
                task_id="",
                status=VideoTaskStatus.FAILED,
                error=f"SSL error: {e}",
            )
        except aiohttp.ClientError as e:
            logger.error(f"[Vidu] Client error: {e}")
            return VideoTask(
                task_id="",
                status=VideoTaskStatus.FAILED,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"[Vidu] Unexpected error: {e}")
            return VideoTask(
                task_id="",
                status=VideoTaskStatus.FAILED,
                error=str(e),
            )

    async def get_task_status(self, task_id: str) -> VideoTask:
        """Poll Vidu task status and get video URL when complete."""
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/tasks/{task_id}/creations"

        connector = aiohttp.TCPConnector()

        try:
            async with aiohttp.ClientSession(connector=connector, timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    status = resp.status
                    text = await resp.text()

                    if status != 200:
                        logger.error(f"[Vidu] Status check error: status={status}, body={text}")
                        return VideoTask(
                            task_id=task_id,
                            status=VideoTaskStatus.FAILED,
                            error=f"HTTP {status}: {text[:200]}",
                        )

                    data = await resp.json()

            state = data.get("state", "")
            progress = data.get("progress", 0)

            if state == "processing":
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.PROCESSING,
                    progress=progress,
                    raw_response=data,
                )
            elif state == "success":
                creations = data.get("creations", [])
                video_url = creations[0].get("url") if creations else None
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.SUCCEEDED,
                    progress=100,
                    video_url=video_url,
                    raw_response=data,
                )
            elif state == "failed":
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.FAILED,
                    error=data.get("err_code", "Unknown error"),
                    raw_response=data,
                )
            else:
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.PENDING,
                    progress=progress,
                    raw_response=data,
                )

        except Exception as e:
            logger.error(f"[Vidu] Status check error: {e}")
            return VideoTask(
                task_id=task_id,
                status=VideoTaskStatus.FAILED,
                error=str(e),
            )

    async def close(self) -> None:
        """No-op - sessions are created per-request."""
        pass
