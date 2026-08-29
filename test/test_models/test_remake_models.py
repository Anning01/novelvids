import pytest
from tortoise.exceptions import IntegrityError

from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from schemas.ai_task import AiTaskOut
from schemas.remake import RemakeSourceOut
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_novel_defaults_to_script_and_persists_project_generation_defaults():
    legacy = await Novel.create(name="既有项目")
    remake = await Novel.create(
        name="重制项目",
        workflow_kind="remake",
        aspect_ratio="9:16",
        resolution="1080p",
        custom_style_prompt="低饱和东方电影质感",
        creation_idempotency_key="55f5842a-7f1a-49d4-b960-b5ea3761343b",
        creation_payload_hash="f" * 64,
    )

    assert legacy.workflow_kind == "script"
    assert legacy.aspect_ratio is None
    assert legacy.resolution is None
    assert remake.workflow_kind == "remake"
    assert remake.aspect_ratio == "9:16"
    assert remake.resolution == "1080p"
    assert remake.custom_style_prompt == "低饱和东方电影质感"

    with pytest.raises(IntegrityError):
        await Novel.create(
            name="重复幂等键项目",
            creation_idempotency_key=remake.creation_idempotency_key,
        )


@pytest.mark.asyncio
async def test_remake_source_has_one_target_chapter_and_unique_episode_per_project():
    novel = await Novel.create(name="多集重制", workflow_kind="remake")
    chapter_one = await Chapter.create(
        novel=novel,
        number=1,
        name="第1集",
        content="",
    )
    chapter_two = await Chapter.create(
        novel=novel,
        number=2,
        name="第2集",
        content="",
    )
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        stage="queued",
        progress=0,
    )
    source = await RemakeSource.create(
        novel=novel,
        chapter=chapter_one,
        episode_number=1,
        source_kind="upload",
        storage_provider="local",
        object_key="remake/sources/source.mp4",
        original_filename="第1集.mp4",
        mime_type="video/mp4",
        size_bytes=1024,
        duration_seconds=10.5,
        width=1920,
        height=1080,
        container_format="mp4",
        checksum="a" * 64,
        analysis_task=task,
    )

    assert source.analysis_task_id == task.id
    assert source.media_status == "ready"
    assert source.source_video_manifest == {}
    source_payload = RemakeSourceOut.model_validate(source)
    assert source_payload.chapter_id == chapter_one.id
    assert source_payload.analysis_task_id == task.id

    with pytest.raises(IntegrityError):
        await RemakeSource.create(
            novel=novel,
            chapter=chapter_two,
            episode_number=1,
            source_kind="upload",
            storage_provider="local",
            object_key="remake/sources/duplicate.mp4",
            original_filename="重复第1集.mp4",
            size_bytes=2048,
            duration_seconds=8,
            width=1280,
            height=720,
            container_format="mp4",
            checksum="b" * 64,
        )

    await task.delete()
    await source.refresh_from_db()
    assert source.analysis_task_id is None


@pytest.mark.asyncio
async def test_ai_task_exposes_remake_stage_and_bounded_progress():
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        stage="detecting_scenes",
        progress=25,
    )

    payload = AiTaskOut.model_validate(task)

    assert AiTaskTypeEnum.remake_decomposition.value == 6
    assert payload.stage == "detecting_scenes"
    assert payload.progress == 25
