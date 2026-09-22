from unittest.mock import AsyncMock

import pytest

from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from services.video.reconciler import VideoTaskReconciler
from utils.enums import TaskStatusEnum, VideoModelTypeEnum


async def _video(scene: Scene, status: TaskStatusEnum, external_task_id: str | None) -> Video:
    return await Video.create(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id=external_task_id,
        status=status.value,
        metadata={},
    )


@pytest.mark.asyncio
async def test_reconcile_once_queries_all_active_provider_tasks():
    novel = await Novel.create(name="自动收口测试")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="正文",
    )
    scene = await Scene.create(
        chapter_id=chapter.id,
        sequence=1,
        prompt="镜头",
        duration=6,
    )
    pending = await _video(scene, TaskStatusEnum.pending, "pending-task")
    running = await _video(scene, TaskStatusEnum.running, "running-task")
    queued = await _video(scene, TaskStatusEnum.queued, "queued-task")
    await _video(scene, TaskStatusEnum.completed, "completed-task")
    await _video(scene, TaskStatusEnum.pending, None)
    query_status = AsyncMock()
    reconciler = VideoTaskReconciler(query_status, interval_seconds=30)

    count = await reconciler.reconcile_once()

    assert count == 3
    assert [call.args[0] for call in query_status.await_args_list] == [
        pending.id,
        running.id,
        queued.id,
    ]
    for video_id in (pending.id, running.id, queued.id):
        refreshed = await Video.get(id=video_id)
        assert refreshed.metadata["last_reconciled_at"]
        assert "last_reconcile_error_type" not in refreshed.metadata


@pytest.mark.asyncio
async def test_reconcile_once_records_error_type_and_keeps_retryable_status():
    novel = await Novel.create(name="自动重试测试")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="正文",
    )
    scene = await Scene.create(
        chapter_id=chapter.id,
        sequence=1,
        prompt="镜头",
        duration=6,
    )
    video = await _video(scene, TaskStatusEnum.pending, "retry-task")
    query_status = AsyncMock(side_effect=RuntimeError("provider details"))
    reconciler = VideoTaskReconciler(query_status, interval_seconds=30)

    count = await reconciler.reconcile_once()

    refreshed = await Video.get(id=video.id)
    assert count == 1
    assert refreshed.status == TaskStatusEnum.pending.value
    assert refreshed.metadata["last_reconcile_error_type"] == "RuntimeError"
    assert refreshed.metadata["reconcile_error_count"] == 1
    assert "provider details" not in str(refreshed.metadata)


@pytest.mark.asyncio
async def test_orphan_submission_expires_without_resubmitting_or_touching_live_reservation():
    from datetime import datetime, timedelta, timezone
    from services.ai_task_executor import TASK_TIMEOUT
    from utils.enums import AiTaskTypeEnum
    from test.test_services.test_creation_object_lifecycle import objects

    _, _, _, scenes = await objects()
    old = await _video(scenes[0], TaskStatusEnum.running, None)
    live = await _video(scenes[1], TaskStatusEnum.running, None)
    for video in [old, live]:
        await Video.filter(id=video.id).update(metadata={'submission_pending': True, 'keep': 'original'})
    await Video.filter(id=old.id).update(created_at=datetime.now(timezone.utc) - timedelta(seconds=TASK_TIMEOUT[AiTaskTypeEnum.video] + 1))
    query = AsyncMock()
    assert await VideoTaskReconciler(query).reconcile_once() == 0
    query.assert_not_awaited()
    await old.refresh_from_db(); await live.refresh_from_db()
    assert old.status == TaskStatusEnum.failed.value
    assert old.metadata['submission_uncertain'] and old.metadata['keep'] == 'original'
    assert 'submission_pending' not in old.metadata
    assert live.status == TaskStatusEnum.running.value and live.metadata['submission_pending']
