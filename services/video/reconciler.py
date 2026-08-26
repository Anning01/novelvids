"""后台持续收口视频供应商异步任务。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from models.video import Video
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)

VideoQuery = Callable[[int], Awaitable[Video]]

_ACTIVE_STATUSES = (
    TaskStatusEnum.pending.value,
    TaskStatusEnum.running.value,
    TaskStatusEnum.queued.value,
)


class VideoTaskReconciler:
    """定期查询未终态视频，让任务生命周期脱离前端页面。"""

    def __init__(
        self,
        query_status: VideoQuery,
        *,
        interval_seconds: int = 30,
        batch_size: int = 50,
    ) -> None:
        self._query_status = query_status
        self._interval_seconds = max(5, int(interval_seconds))
        self._batch_size = max(1, int(batch_size))
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self.run(),
            name="video-task-reconciler",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "Video task reconciliation cycle failed: error_type=%s",
                    type(error).__name__,
                )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue

    async def reconcile_once(self) -> int:
        candidates = await Video.filter(
            status__in=_ACTIVE_STATUSES,
            external_task_id__not_isnull=True,
        ).order_by("updated_at", "id").limit(self._batch_size)
        for candidate in candidates:
            if not candidate.external_task_id:
                continue
            try:
                await self._query_status(candidate.id)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "Video task reconciliation failed: video_id=%s error_type=%s",
                    candidate.id,
                    type(error).__name__,
                )
                await self._record_attempt(candidate.id, error_type=type(error).__name__)
            else:
                await self._record_attempt(candidate.id)
        return len(candidates)

    @staticmethod
    async def _record_attempt(video_id: int, error_type: str | None = None) -> None:
        video = await Video.get_or_none(id=video_id)
        if video is None:
            return
        metadata = video.metadata if isinstance(video.metadata, dict) else {}
        reconcile_metadata = {
            **metadata,
            "last_reconciled_at": datetime.now(timezone.utc).isoformat(),
        }
        if error_type:
            reconcile_metadata["last_reconcile_error_type"] = error_type
            try:
                error_count = int(metadata.get("reconcile_error_count", 0) or 0)
            except (TypeError, ValueError):
                error_count = 0
            reconcile_metadata["reconcile_error_count"] = error_count + 1
        else:
            reconcile_metadata.pop("last_reconcile_error_type", None)
            reconcile_metadata.pop("reconcile_error_count", None)
        video.metadata = reconcile_metadata
        await video.save(update_fields=["metadata", "updated_at"])
