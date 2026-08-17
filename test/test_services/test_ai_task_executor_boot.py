"""服务启动清理遗留任务：重启后 pending/running 任务自动失败且不产生计费流水。"""

import pytest

from models.ai_task import AiTask
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services.ai_task_executor import ai_task_executor
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_fail_stale_on_boot_marks_legacy_tasks_failed():
    novel = await Novel.create(name="启动清理项目", author="x")
    stale_pending = await AiTask.create(
        task_type=AiTaskTypeEnum.project_analysis.value,
        status=TaskStatusEnum.pending.value,
        request_params={"novel_id": novel.id},
    )
    stale_running = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"novel_id": novel.id},
    )
    completed = await AiTask.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        status=TaskStatusEnum.completed.value,
        request_params={"novel_id": novel.id},
    )
    # 视频类型不归执行器管，不应被启动清理误伤
    video_task = await AiTask.create(
        task_type=AiTaskTypeEnum.video.value,
        status=TaskStatusEnum.pending.value,
        request_params={"novel_id": novel.id},
    )

    await ai_task_executor.fail_stale_on_boot()

    pending = await AiTask.get(id=stale_pending.id)
    assert pending.status == TaskStatusEnum.failed.value
    assert "服务重启" in pending.error_message

    running = await AiTask.get(id=stale_running.id)
    assert running.status == TaskStatusEnum.failed.value

    assert (await AiTask.get(id=completed.id)).status == TaskStatusEnum.completed.value
    assert (await AiTask.get(id=video_task.id)).status == TaskStatusEnum.pending.value

    # 启动清理不计费：不产生任何流水
    assert await ModelUsageRecord.filter(novel_id=novel.id).count() == 0


@pytest.mark.asyncio
async def test_fail_stale_on_boot_idempotent_on_clean_db():
    await ai_task_executor.fail_stale_on_boot()
    await ai_task_executor.fail_stale_on_boot()
