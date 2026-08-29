import pytest

from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from services.remake.progress import RemakeProgressService
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


async def create_source(novel, episode_number, *, status, stage, progress):
    chapter = await Chapter.create(
        novel=novel,
        number=episode_number,
        name=f"第{episode_number}集",
        content="",
    )
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=status,
        stage=stage,
        progress=progress,
    )
    return await RemakeSource.create(
        novel=novel,
        chapter=chapter,
        episode_number=episode_number,
        source_kind="upload",
        storage_provider="local",
        object_key=f"remake/{episode_number}.mp4",
        original_filename=f"第{episode_number}集.mp4",
        mime_type="video/mp4",
        size_bytes=1024,
        duration_seconds=12,
        width=1080,
        height=1920,
        container_format="mp4",
        checksum=str(episode_number) * 64,
        media_status="processing",
        analysis_task=task,
    )


@pytest.mark.asyncio
async def test_project_progress_is_recoverable_from_persisted_tasks():
    novel = await Novel.create(
        name="进度快照项目",
        author="重制工坊",
        workflow_kind="remake",
    )
    await create_source(
        novel,
        1,
        status=TaskStatusEnum.completed.value,
        stage="completed",
        progress=100,
    )
    await create_source(
        novel,
        2,
        status=TaskStatusEnum.running.value,
        stage="detecting_scenes",
        progress=42,
    )

    snapshot = await RemakeProgressService().snapshot(novel)

    assert snapshot["aggregate_status"] == "processing"
    assert snapshot["terminal"] is False
    assert snapshot["overall_progress"] == 71
    assert snapshot["source_summary"] == {
        "total": 2,
        "queued": 0,
        "processing": 1,
        "completed": 1,
        "failed": 0,
    }
    assert snapshot["sources"][1]["task"]["stage"] == "detecting_scenes"
    assert snapshot["entry_path"].endswith(str(novel.id))


@pytest.mark.asyncio
async def test_project_progress_becomes_terminal_when_every_source_finishes():
    novel = await Novel.create(
        name="已完成进度项目",
        author="重制工坊",
        workflow_kind="remake",
    )
    await create_source(
        novel,
        1,
        status=TaskStatusEnum.completed.value,
        stage="completed",
        progress=99,
    )

    snapshot = await RemakeProgressService().snapshot(novel)

    assert snapshot["aggregate_status"] == "completed"
    assert snapshot["terminal"] is True
    assert snapshot["overall_progress"] == 100
