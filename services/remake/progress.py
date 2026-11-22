"""重制项目拆解进度的持久化快照。"""

from __future__ import annotations

from collections import defaultdict
from tortoise.expressions import Q
from models.agent_operation import AgentOperation
from services.remake.customer_errors import failure_message
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from services.remake.checkpoints import ASSET_RECEIPT_KEYS
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

        receipts = defaultdict(list)
        inspect_ids = [s.analysis_task_id for s in sources if s.analysis_task and
                       s.analysis_task.status != TaskStatusEnum.completed and
                       (s.analysis_task.status in self._FAILED or s.analysis_task.progress >= 42 or s.analysis_task.request_params.get('retry_of_task_id'))]
        if inspect_ids:
            for task_id, key, state in await AgentOperation.filter(
                Q(key__startswith="model:remake:") | Q(key__startswith="capacity:remake:"), task_id__in=inspect_ids
            ).values_list("task_id", "key", "state"):
                receipts[task_id].append((key, state))

        failed_chapters = [s.chapter_id for s in sources if s.analysis_task and s.analysis_task.status in self._FAILED]
        saved_counts = defaultdict(int)
        if failed_chapters:
            rows = await Scene.filter(chapter_id__in=failed_chapters, deleted_at=None).exclude(prompt__isnull=True).exclude(prompt="").values_list("chapter_id", "metadata")
            for chapter_id, metadata in rows:
                saved_counts[chapter_id, (metadata or {}).get("remake_source_id")] += 1

        for source in sources:
            task = source.analysis_task
            status = task.status if task else None
            if task is None and source.media_status == "completed":
                status = TaskStatusEnum.completed.value
            progress = max(0, min(100, int(task.progress or 0))) if task else 0
            completed_clips, total_clips = 0, None
            shot_states = {}
            if task and status == TaskStatusEnum.completed:
                total_clips = ((task.response_data or {}).get('pipeline') or {}).get('shot_count')
                completed_clips = total_clips or 0
            if task and status != TaskStatusEnum.completed and (progress >= 42 or task.request_params.get('retry_of_task_id')):
                from services.remake.checkpoints import shot_progress
                _, saved_progress, completed_clips, total_clips, shot_states = await shot_progress(task, source, receipts[task.id])
                progress = max(progress, saved_progress)
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
            failed_stage = None
            if status == TaskStatusEnum.failed:
                asset_states = {state for key, state in receipts[task.id] if key in ASSET_RECEIPT_KEYS}
                if 'failed' in asset_states and 'completed' not in asset_states:
                    failed_stage = 'extracting_assets'
            awaiting = bool(task and task.request_params.get('remake_context_version') and
                            (task.stage == 'needs_review' or 'uncertain' in shot_states.values()))
            retryable = 0
            if task and status == TaskStatusEnum.failed:
                from services.remake.checkpoints import partial_retry
                held, retryable = await partial_retry(task, total_clips)
            else:
                held = []
            source_items.append(
                {
                    "source_id": source.id,
                    "chapter_id": source.chapter_id,
                    "episode_number": source.episode_number,
                    "original_filename": source.original_filename,
                    "media_status": source.media_status,
                    "saved_scene_count": saved_counts[source.chapter_id, source.id] if status in self._FAILED else None,
                    "task": (
                        {
                            "id": str(task.id),
                            "status": task.status,
                            "stage": task.stage or "queued",
                            "progress": progress,
                            "completed_clips": completed_clips,
                            "shot_states": shot_states,
                            "total_clips": total_clips,
                            "error_message": await failure_message(task, failed_stage=failed_stage),
                            "failed_stage": failed_stage,
                            "awaiting_platform_result": awaiting,
                            "retryable_clips": retryable,
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
