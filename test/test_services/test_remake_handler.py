from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from services.remake.gateway import RemakeVideoAnalysisError
from services.remake.handler import RemakeDecompositionError, RemakeDecompositionTaskHandler
from services.remake.pipeline import RemakePipelineResult
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


async def _records(tmp_path: Path):
    novel = await Novel.create(
        name="处理器项目",
        author="tester",
        description="",
        content="",
        total_chapters=1,
        workflow_kind="remake",
    )
    chapter = await Chapter.create(novel=novel, number=1, name="第1集", content="")
    source = await RemakeSource.create(
        novel=novel,
        chapter=chapter,
        episode_number=1,
        source_kind="upload",
        storage_provider="local",
        object_key="remake/sources/source.mp4",
        original_filename="source.mp4",
        mime_type="video/mp4",
        size_bytes=10,
        duration_seconds=4,
        width=1280,
        height=720,
        container_format="mp4",
        checksum="a" * 64,
    )
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.running.value,
        stage="queued",
        request_params={},
    )
    return novel, chapter, source, task


class _Materializer:
    def __init__(self, path: Path):
        self.path = path
        self.calls = []

    async def materialize(self, source, work_dir):
        self.calls.append((source.id, work_dir))
        return self.path


class _Pipeline:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        for value, stage in ((10, "preparing"), (55, "generating_storyboards"), (88, "persisting")):
            await kwargs["progress"](value, stage)
        return self.result


class _Persistence:
    def __init__(self):
        self.calls = []

    async def persist(self, **kwargs):
        self.calls.append(kwargs)
        kwargs["source"].media_status = "completed"
        await kwargs["source"].save(update_fields=["media_status", "updated_at"])
        return {"asset_count": 1, "scene_count": 1}


@pytest.mark.asyncio
async def test_handler_runs_controlled_pipeline_updates_progress_and_returns_billing_metadata(tmp_path: Path):
    novel, chapter, source, task = await _records(tmp_path)
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    config = SimpleNamespace(id=12, name="理解模型", model="vision-model")
    result = RemakePipelineResult(
        assets={"characters": [], "scenes": [], "objects": []},
        prompt_document={"prompts": []},
        metadata={"pipeline": "global_assets_professional_prompts_v4"},
        token_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )
    pipeline = _Pipeline(result=result)
    persistence = _Persistence()

    async def resolve(task_type, config_id=None, team_id=None):
        assert task_type == AiTaskTypeEnum.remake_decomposition.value
        assert config_id is None
        return config

    handler = RemakeDecompositionTaskHandler(
        model_resolver=resolve,
        materializer=_Materializer(source_path),
        pipeline=pipeline,
        persistence=persistence,
    )
    response = await handler.execute(
        {
            "ai_task_id": str(task.id),
            "novel_id": novel.id,
            "chapter_id": chapter.id,
            "remake_source_id": source.id,
            "team_id": None,
            "attempt": 1,
        }
    )

    await task.refresh_from_db()
    await source.refresh_from_db()
    assert task.stage == "persisting"
    assert task.progress == 88
    assert task.request_params["model_config_id"] == 12
    assert task.request_params["model"] == "vision-model"
    assert source.media_status == "completed"
    assert response == {
        "asset_count": 1,
        "scene_count": 1,
        "pipeline": {"pipeline": "global_assets_professional_prompts_v4"},
        "token_usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "llm_config_id": 12,
        "llm_model": "vision-model",
    }
    assert persistence.calls[0]["source"].id == source.id


@pytest.mark.asyncio
async def test_handler_marks_source_failed_and_returns_content_free_error(tmp_path: Path):
    novel, chapter, source, task = await _records(tmp_path)
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")

    async def resolve(*_args, **_kwargs):
        return SimpleNamespace(id=12, name="理解模型", model="vision-model")

    handler = RemakeDecompositionTaskHandler(
        model_resolver=resolve,
        materializer=_Materializer(source_path),
        pipeline=_Pipeline(error=RuntimeError("provider secret response")),
        persistence=_Persistence(),
    )

    with pytest.raises(RemakeDecompositionError) as raised:
        await handler.execute(
            {
                "ai_task_id": str(task.id),
                "novel_id": novel.id,
                "chapter_id": chapter.id,
                "remake_source_id": source.id,
                "team_id": None,
            }
        )

    await source.refresh_from_db()
    assert source.media_status == "failed"
    assert str(raised.value) == "重制视频拆解失败（错误代码：REMAKE_ANALYSIS_FAILED）"
    assert "provider" not in str(raised.value)


@pytest.mark.asyncio
async def test_handler_reports_missing_analysis_model_with_stable_retryable_code(tmp_path: Path):
    novel, chapter, source, task = await _records(tmp_path)
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")

    async def resolve(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="raw controller detail")

    handler = RemakeDecompositionTaskHandler(
        model_resolver=resolve,
        materializer=_Materializer(source_path),
        pipeline=_Pipeline(),
        persistence=_Persistence(),
    )

    with pytest.raises(RemakeDecompositionError) as raised:
        await handler.execute(
            {
                "ai_task_id": str(task.id),
                "novel_id": novel.id,
                "chapter_id": chapter.id,
                "remake_source_id": source.id,
                "team_id": None,
            }
        )

    assert raised.value.error_code == "REMAKE_ANALYSIS_MODEL_UNAVAILABLE"
    assert "raw controller" not in str(raised.value)


@pytest.mark.asyncio
async def test_handler_preserves_safe_video_analysis_failure_category(tmp_path: Path):
    novel, chapter, source, task = await _records(tmp_path)
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")

    async def resolve(*_args, **_kwargs):
        return SimpleNamespace(id=12, name="理解模型", model="vision-model")

    handler = RemakeDecompositionTaskHandler(
        model_resolver=resolve,
        materializer=_Materializer(source_path),
        pipeline=_Pipeline(
            error=RemakeVideoAnalysisError(
                "视频分析请求与当前模型能力不兼容",
                error_code="REMAKE_ANALYSIS_REQUEST_INVALID",
            )
        ),
        persistence=_Persistence(),
    )

    with pytest.raises(RemakeDecompositionError) as raised:
        await handler.execute(
            {
                "ai_task_id": str(task.id),
                "novel_id": novel.id,
                "chapter_id": chapter.id,
                "remake_source_id": source.id,
                "team_id": None,
            }
        )

    assert raised.value.error_code == "REMAKE_ANALYSIS_REQUEST_INVALID"
    assert "当前模型能力不兼容" in str(raised.value)
