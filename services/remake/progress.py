"""重制项目拆解进度的持久化快照。"""

from __future__ import annotations

from models.novel import Novel
from models.remake_source import RemakeSource
from utils.enums import TaskStatusEnum


class RemakeProgressService:
    """从数据库组装项目级进度；SSE 连接不拥有也不控制后台任务。"""

    _QUEUED = {
        TaskStatusEnum.queued.value,
        TaskStatusEnum.pending.value,
    }
    _FAILED = {
        TaskStatusEnum.failed.value,
        TaskStatusEnum.cancelled.value,
    }

    async def snapshot(self, novel: Novel) -> dict:
        sources = await RemakeSource.filter(novel_id=novel.id).order_by(
            "episode_number", "id"
        ).select_related("analysis_task")
        summary = {
            "total": len(sources),
            "queued": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
        }
        source_items: list[dict] = []
        progress_values: list[int] = []
        versions = [novel.updated_at]

        for source in sources:
            task = source.analysis_task
            status = task.status if task else None
            progress = max(0, min(100, int(task.progress or 0))) if task else 0
            if status in self._QUEUED:
                summary["queued"] += 1
            elif status == TaskStatusEnum.running.value:
                summary["processing"] += 1
            elif status == TaskStatusEnum.completed.value:
                summary["completed"] += 1
                progress = 100
            elif status in self._FAILED:
                summary["failed"] += 1
            else:
                summary["queued"] += 1
            progress_values.append(progress)
            versions.append(source.updated_at)
            if task is not None:
                versions.append(task.updated_at)
            source_items.append(
                {
                    "source_id": source.id,
                    "chapter_id": source.chapter_id,
                    "episode_number": source.episode_number,
                    "original_filename": source.original_filename,
                    "media_status": source.media_status,
                    "task": (
                        {
                            "id": str(task.id),
                            "status": task.status,
                            "stage": task.stage or "queued",
                            "progress": progress,
                            "error_message": task.error_message,
                            "updated_at": task.updated_at.isoformat(),
                        }
                        if task is not None
                        else None
                    ),
                }
            )

        total = summary["total"]
        terminal_count = summary["completed"] + summary["failed"]
        if total and summary["completed"] == total:
            aggregate_status = "completed"
        elif total and summary["failed"] == total:
            aggregate_status = "failed"
        elif summary["failed"]:
            aggregate_status = "partial_failed"
        elif summary["processing"] or summary["completed"]:
            aggregate_status = "processing"
        else:
            aggregate_status = "queued"

        return {
            "novel_id": novel.id,
            "name": novel.name,
            "aggregate_status": aggregate_status,
            "terminal": bool(total and terminal_count == total),
            "overall_progress": (
                round(sum(progress_values) / len(progress_values))
                if progress_values
                else 0
            ),
            "source_summary": summary,
            "sources": source_items,
            "entry_path": f"/create/short-drama/manual/{novel.id}",
            "updated_at": max(versions).isoformat(),
        }


remake_progress_service = RemakeProgressService()
