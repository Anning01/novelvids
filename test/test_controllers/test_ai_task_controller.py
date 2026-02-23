import uuid

import pytest
from fastapi import HTTPException

from controllers.ai_task import ai_task_controller
from models.ai_task import AiTask
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_查询存在的任务():
    """根据 UUID 查询已存在的任务。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": 1},
    )

    result = await ai_task_controller.get(task.id)
    assert result.id == task.id
    assert result.task_type == AiTaskTypeEnum.extraction.value
    assert result.status == TaskStatusEnum.pending.value


@pytest.mark.asyncio
async def test_查询不存在的任务_抛出404():
    """查询一个不存在的 UUID 应抛出 HTTPException 404。"""
    fake_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await ai_task_controller.get(fake_id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_取消pending任务():
    """pending 状态的任务可以取消。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": 1},
    )

    result = await ai_task_controller.cancel(task.id)
    assert result.status == TaskStatusEnum.cancelled.value

    # 数据库也应更新
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.cancelled.value


@pytest.mark.asyncio
async def test_取消running任务():
    """running 状态的任务可以取消。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": 1},
    )

    result = await ai_task_controller.cancel(task.id)
    assert result.status == TaskStatusEnum.cancelled.value


@pytest.mark.asyncio
async def test_取消已完成任务_抛出400():
    """completed 状态的任务不能取消。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.completed.value,
        request_params={"chapter_id": 1},
    )

    with pytest.raises(HTTPException) as exc_info:
        await ai_task_controller.cancel(task.id)
    assert exc_info.value.status_code == 400
    assert "不可取消" in exc_info.value.detail


@pytest.mark.asyncio
async def test_取消已失败任务_抛出400():
    """failed 状态的任务不能取消。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.failed.value,
        request_params={"chapter_id": 1},
        error_message="some error",
    )

    with pytest.raises(HTTPException) as exc_info:
        await ai_task_controller.cancel(task.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_取消已取消任务_抛出400():
    """cancelled 状态的任务不能再次取消。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.cancelled.value,
        request_params={"chapter_id": 1},
    )

    with pytest.raises(HTTPException) as exc_info:
        await ai_task_controller.cancel(task.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_取消不存在任务_抛出404():
    """取消不存在的任务应抛出 404。"""
    fake_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await ai_task_controller.cancel(fake_id)
    assert exc_info.value.status_code == 404
