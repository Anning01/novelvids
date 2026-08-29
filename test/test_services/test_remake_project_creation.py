from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import UploadFile

from exceptions.remake import RemakeError
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from schemas.remake import RemakeProjectCreate
from services.remake.media import ValidatedRemakeMedia
from services.remake.history_snapshot import HistorySnapshot
from services.remake.projects import RemakeProjectService
from services.remake.uploads import RemakeUploadService
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class FakeValidator:
    def validate_extension(self, filename):
        return None

    def validate_path(self, path, *, original_filename, mime_type=None):
        return ValidatedRemakeMedia(
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
            duration_seconds=10,
            width=1280,
            height=720,
            container_format="mp4",
            checksum="d" * 64,
        )


class LocalProvider:
    enabled = False
    name = "local"


class CleanupFailingUploadService(RemakeUploadService):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.rollback_calls = 0

    async def rollback_promotion(self, promotion) -> None:
        self.rollback_calls += 1
        await super().rollback_promotion(promotion)
        if self.rollback_calls == 1:
            raise RuntimeError("simulated cleanup failure")


class FakeHistorySnapshotService:
    def __init__(self, *, fail: RemakeError | None = None) -> None:
        self.fail = fail
        self.created: list[tuple[int, int | None]] = []
        self.cleaned: list[HistorySnapshot] = []

    async def create(self, chapter, *, team_id):
        self.created.append((chapter.id, team_id))
        if self.fail is not None:
            raise self.fail
        media = ValidatedRemakeMedia(
            original_filename=f"第{chapter.number}集-历史快照.mp4",
            mime_type="video/mp4",
            size_bytes=12,
            duration_seconds=9,
            width=1080,
            height=1920,
            container_format="mp4",
            checksum="e" * 64,
        )
        return HistorySnapshot(
            storage_provider="local",
            object_key=f"remake/sources/history/{chapter.id}.mp4",
            original_filename=media.original_filename,
            media=media,
            source_novel_id=chapter.novel_id,
            source_chapter_id=chapter.id,
            manifest={
                "source_novel_id": chapter.novel_id,
                "source_chapter_id": chapter.id,
                "components": [{"scene_id": 7, "video_id": 9, "sequence": 1}],
            },
        )

    async def cleanup(self, snapshot):
        self.cleaned.append(snapshot)


async def ready_upload(service: RemakeUploadService, filename: str = "demo.mp4"):
    return await service.stage_local(
        UploadFile(
            filename=filename,
            file=BytesIO(b"video"),
            headers={"content-type": "video/mp4"},
        ),
        team_id=3,
        user_id=5,
    )


def payload(upload_id, *, key=None, name="单视频重制"):
    return RemakeProjectCreate(
        name=name,
        source_mode="single_upload",
        aspect_ratio="9:16",
        resolution="720p",
        style_key="realistic-general",
        custom_style_prompt=None,
        idempotency_key=key or uuid4(),
        sources=[{"episode_number": 1, "upload_token": upload_id}],
    )


def history_payload(chapter_id, *, key=None, name="历史视频重制"):
    return RemakeProjectCreate(
        name=name,
        source_mode="history",
        aspect_ratio="9:16",
        resolution="720p",
        style_key="realistic-general",
        custom_style_prompt=None,
        idempotency_key=key or uuid4(),
        sources=[{"source_chapter_id": chapter_id}],
    )


def folder_payload(sources, *, key=None, name="文件夹重制"):
    return RemakeProjectCreate(
        name=name,
        source_mode="folder_upload",
        aspect_ratio="9:16",
        resolution="720p",
        style_key="realistic-general",
        custom_style_prompt=None,
        idempotency_key=key or uuid4(),
        sources=sources,
    )


@pytest.mark.asyncio
async def test_single_upload_creation_is_atomic_and_creates_one_decomposition_task(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    upload = await ready_upload(upload_service)
    service = RemakeProjectService(upload_service=upload_service)

    result = await service.create(payload(upload.id), team_id=3, user_id=5)

    novel = await Novel.get(id=result["novel_id"])
    chapter = await Chapter.get(novel=novel)
    source = await RemakeSource.get(novel=novel)
    task = await AiTask.get(id=source.analysis_task_id)
    await upload.refresh_from_db()

    assert novel.workflow_kind == "remake"
    assert novel.total_chapters == 1
    assert chapter.number == 1
    assert source.episode_number == 1
    assert source.object_key.startswith("remake/sources/")
    assert task.task_type == AiTaskTypeEnum.remake_decomposition.value
    assert task.status == TaskStatusEnum.queued.value
    assert task.stage == "queued"
    assert task.request_params["ai_task_id"] == str(task.id)
    assert upload.status == "committed"
    assert (tmp_path / source.object_key).exists()


@pytest.mark.asyncio
async def test_project_creation_checks_balance_before_committing_media(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    upload = await ready_upload(upload_service)
    calls = []

    async def check_balance(team_id, user_id):
        calls.append((team_id, user_id))

    service = RemakeProjectService(
        upload_service=upload_service,
        balance_checker=check_balance,
    )

    await service.create(payload(upload.id), team_id=3, user_id=5)

    assert calls == [(3, 5)]


@pytest.mark.asyncio
async def test_same_idempotency_key_returns_original_project_and_conflicting_payload_is_rejected(
    tmp_path,
):
    upload_service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    upload = await ready_upload(upload_service)
    service = RemakeProjectService(upload_service=upload_service)
    key = uuid4()
    request = payload(upload.id, key=key)

    first = await service.create(request, team_id=3, user_id=5)
    second = await service.create(request, team_id=3, user_id=5)

    assert first == second
    assert await Novel.filter(workflow_kind="remake").count() == 1
    assert await RemakeSource.all().count() == 1

    with pytest.raises(RemakeError) as exc_info:
        await service.create(
            payload(upload.id, key=key, name="不同名称"),
            team_id=3,
            user_id=5,
        )
    assert exc_info.value.error_code == "REMAKE_IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_single_mode_rejects_multiple_or_unowned_uploads(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    upload = await ready_upload(upload_service)
    service = RemakeProjectService(upload_service=upload_service)

    request = payload(upload.id)
    request.sources.append(request.sources[0].model_copy())
    with pytest.raises(RemakeError) as mismatch:
        await service.create(request, team_id=3, user_id=5)
    assert mismatch.value.error_code == "REMAKE_SOURCE_MODE_MISMATCH"

    with pytest.raises(RemakeError) as forbidden:
        await service.create(payload(upload.id), team_id=3, user_id=6)
    assert forbidden.value.error_code == "REMAKE_UPLOAD_NOT_FOUND"


@pytest.mark.asyncio
async def test_history_creation_persists_snapshot_audit_and_uses_source_episode_number(
    tmp_path,
):
    source_novel = await Novel.create(name="旧项目", author="作者", team_id=3)
    source_chapter = await Chapter.create(
        novel=source_novel,
        number=4,
        name="第4集",
        content="",
    )
    snapshots = FakeHistorySnapshotService()
    service = RemakeProjectService(history_snapshot_service=snapshots)

    result = await service.create(
        history_payload(source_chapter.id),
        team_id=3,
        user_id=5,
    )

    novel = await Novel.get(id=result["novel_id"])
    chapter = await Chapter.get(novel=novel)
    source = await RemakeSource.get(novel=novel)
    assert novel.description == "重制工坊 · 历史项目"
    assert chapter.number == 4
    assert source.source_kind == "history"
    assert source.storage_provider == "local"
    assert source.source_novel_id == source_novel.id
    assert source.source_chapter_id == source_chapter.id
    assert source.source_video_manifest["components"][0]["video_id"] == 9
    assert snapshots.created == [(source_chapter.id, 3)]


@pytest.mark.asyncio
async def test_history_creation_rejects_cross_team_source_before_snapshot(tmp_path):
    source_novel = await Novel.create(name="其他团队项目", author="作者", team_id=8)
    source_chapter = await Chapter.create(
        novel=source_novel,
        number=1,
        name="第1集",
        content="",
    )
    snapshots = FakeHistorySnapshotService()
    service = RemakeProjectService(history_snapshot_service=snapshots)

    with pytest.raises(RemakeError) as caught:
        await service.create(
            history_payload(source_chapter.id),
            team_id=3,
            user_id=5,
        )

    assert caught.value.error_code == "REMAKE_HISTORY_PROJECT_FORBIDDEN"
    assert caught.value.status_code == 403
    assert snapshots.created == []


@pytest.mark.asyncio
async def test_history_snapshot_is_cleaned_when_project_transaction_fails(tmp_path):
    await Novel.create(name="名称冲突", author="作者", team_id=3)
    source_novel = await Novel.create(name="事务旧项目", author="作者", team_id=3)
    source_chapter = await Chapter.create(
        novel=source_novel,
        number=1,
        name="第1集",
        content="",
    )
    snapshots = FakeHistorySnapshotService()
    service = RemakeProjectService(history_snapshot_service=snapshots)

    with pytest.raises(RemakeError) as caught:
        await service.create(
            history_payload(source_chapter.id, name="名称冲突"),
            team_id=3,
            user_id=5,
        )

    assert caught.value.error_code == "REMAKE_PROJECT_CONFIG_INVALID"
    assert len(snapshots.cleaned) == 1
    assert await RemakeSource.all().count() == 0


@pytest.mark.asyncio
async def test_folder_creation_sorts_three_episodes_and_creates_independent_tasks(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    third = await ready_upload(upload_service, "第3集.mp4")
    first = await ready_upload(upload_service, "EP01.mov")
    second = await ready_upload(upload_service, "第2话.mp4")
    service = RemakeProjectService(upload_service=upload_service)

    result = await service.create(
        folder_payload([
            {"episode_number": 3, "upload_token": third.id},
            {"episode_number": 1, "upload_token": first.id},
            {"episode_number": 2, "upload_token": second.id},
        ]),
        team_id=3,
        user_id=5,
    )

    assert [item["episode_number"] for item in result["sources"]] == [1, 2, 3]
    assert result["warnings"] == []
    assert await Chapter.filter(novel_id=result["novel_id"]).count() == 3
    assert await RemakeSource.filter(novel_id=result["novel_id"]).count() == 3
    assert len({item["task_id"] for item in result["sources"]}) == 3
    for upload in (first, second, third):
        await upload.refresh_from_db()
        assert upload.status == "committed"


@pytest.mark.asyncio
async def test_folder_creation_returns_gap_warning_without_blocking(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(), provider=LocalProvider(), media_root=tmp_path
    )
    first = await ready_upload(upload_service, "第1集.mp4")
    third = await ready_upload(upload_service, "第3集.mp4")
    service = RemakeProjectService(upload_service=upload_service)

    result = await service.create(
        folder_payload([
            {"episode_number": 3, "upload_token": third.id},
            {"episode_number": 1, "upload_token": first.id},
        ]),
        team_id=3,
        user_id=5,
    )

    assert result["warnings"] == [{
        "code": "REMAKE_EPISODE_GAPS",
        "missing_episode_numbers": [2],
    }]


@pytest.mark.asyncio
async def test_folder_creation_revalidates_filename_episode_and_duplicate_batch(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(), provider=LocalProvider(), media_root=tmp_path
    )
    first = await ready_upload(upload_service, "第1集.mp4")
    duplicate = await ready_upload(upload_service, "EP01.mov")
    service = RemakeProjectService(upload_service=upload_service)

    with pytest.raises(RemakeError) as duplicated:
        await service.create(
            folder_payload([
                {"episode_number": 1, "upload_token": first.id},
                {"episode_number": 1, "upload_token": duplicate.id},
            ]),
            team_id=3,
            user_id=5,
        )
    assert duplicated.value.error_code == "REMAKE_EPISODE_DUPLICATED"

    with pytest.raises(RemakeError) as mismatch:
        await service.create(
            folder_payload([{"episode_number": 2, "upload_token": first.id}]),
            team_id=3,
            user_id=5,
        )
    assert mismatch.value.error_code == "REMAKE_SOURCE_MODE_MISMATCH"
    await first.refresh_from_db()
    assert first.status == "ready"


@pytest.mark.asyncio
async def test_folder_transaction_failure_rolls_back_every_promoted_upload(tmp_path):
    await Novel.create(name="多集名称冲突", author="作者")
    upload_service = RemakeUploadService(
        validator=FakeValidator(), provider=LocalProvider(), media_root=tmp_path
    )
    first = await ready_upload(upload_service, "第1集.mp4")
    second = await ready_upload(upload_service, "第2集.mp4")
    original_keys = {first.id: first.object_key, second.id: second.object_key}
    service = RemakeProjectService(upload_service=upload_service)

    with pytest.raises(RemakeError):
        await service.create(
            folder_payload(
                [
                    {"episode_number": 1, "upload_token": first.id},
                    {"episode_number": 2, "upload_token": second.id},
                ],
                name="多集名称冲突",
            ),
            team_id=3,
            user_id=5,
        )

    for upload in (first, second):
        await upload.refresh_from_db()
        assert upload.status == "ready"
        assert upload.object_key == original_keys[upload.id]
        assert (tmp_path / upload.object_key).exists()
    assert await RemakeSource.all().count() == 0


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_mask_transaction_error_or_skip_siblings(tmp_path):
    await Novel.create(name="清理失败名称冲突", author="作者")
    upload_service = CleanupFailingUploadService(
        validator=FakeValidator(), provider=LocalProvider(), media_root=tmp_path
    )
    first = await ready_upload(upload_service, "第1集.mp4")
    second = await ready_upload(upload_service, "第2集.mp4")
    service = RemakeProjectService(upload_service=upload_service)

    with pytest.raises(RemakeError) as caught:
        await service.create(
            folder_payload(
                [
                    {"episode_number": 1, "upload_token": first.id},
                    {"episode_number": 2, "upload_token": second.id},
                ],
                name="清理失败名称冲突",
            ),
            team_id=3,
            user_id=5,
        )

    assert caught.value.error_code == "REMAKE_PROJECT_CONFIG_INVALID"
    assert upload_service.rollback_calls == 2
    for upload in (first, second):
        await upload.refresh_from_db()
        assert upload.status == "ready"
        assert (tmp_path / upload.object_key).exists()


@pytest.mark.asyncio
async def test_one_folder_episode_failure_and_retry_does_not_change_sibling_task(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(), provider=LocalProvider(), media_root=tmp_path
    )
    first = await ready_upload(upload_service, "第1集.mp4")
    second = await ready_upload(upload_service, "第2集.mp4")
    service = RemakeProjectService(upload_service=upload_service)
    result = await service.create(
        folder_payload([
            {"episode_number": 1, "upload_token": first.id},
            {"episode_number": 2, "upload_token": second.id},
        ]),
        team_id=3,
        user_id=5,
    )
    failed_source = await RemakeSource.get(id=result["sources"][0]["source_id"])
    sibling_source = await RemakeSource.get(id=result["sources"][1]["source_id"])
    failed_task = await AiTask.get(id=failed_source.analysis_task_id)
    sibling_task_id = sibling_source.analysis_task_id
    failed_task.status = TaskStatusEnum.failed.value
    await failed_task.save(update_fields=["status", "updated_at"])
    failed_source.media_status = "failed"
    await failed_source.save(update_fields=["media_status", "updated_at"])

    retried = await service.retry(failed_source.id, team_id=3, user_id=5)

    await sibling_source.refresh_from_db()
    assert retried["task_id"] != failed_task.id
    assert sibling_source.analysis_task_id == sibling_task_id
    assert (await AiTask.get(id=sibling_task_id)).status == TaskStatusEnum.queued.value


@pytest.mark.asyncio
async def test_failed_decomposition_can_retry_once_with_incremented_attempt(tmp_path):
    upload_service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    upload = await ready_upload(upload_service)
    service = RemakeProjectService(upload_service=upload_service)
    created = await service.create(payload(upload.id), team_id=3, user_id=5)
    source = await RemakeSource.get(id=created["sources"][0]["source_id"])
    old_task = await AiTask.get(id=source.analysis_task_id)
    old_task.status = TaskStatusEnum.failed.value
    await old_task.save(update_fields=["status", "updated_at"])
    source.media_status = "failed"
    await source.save(update_fields=["media_status", "updated_at"])

    result = await service.retry(source.id, team_id=3, user_id=5)

    await source.refresh_from_db()
    task = await AiTask.get(id=result["task_id"])
    assert task.id != old_task.id
    assert task.status == TaskStatusEnum.queued.value
    assert task.request_params["attempt"] == 2
    assert task.request_params["ai_task_id"] == str(task.id)
    assert task.request_params["retry_of_task_id"] == str(old_task.id)
    assert source.analysis_task_id == task.id
    assert source.media_status == "ready"

    with pytest.raises(RemakeError) as exc_info:
        await service.retry(source.id, team_id=3, user_id=5)
    assert exc_info.value.error_code == "REMAKE_ANALYSIS_NOT_RETRYABLE"
