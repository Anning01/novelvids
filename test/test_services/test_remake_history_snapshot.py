from pathlib import Path

import pytest

from exceptions.remake import RemakeError
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from services.remake.history import RemakeHistoryCatalog
from services.remake.history_snapshot import RemakeHistorySnapshotService
from services.remake.media import ValidatedRemakeMedia
from utils.enums import TaskStatusEnum, VideoModelTypeEnum


class FakeMerger:
    def merge_paths(self, video_paths: list[str], output_path: str) -> None:
        Path(output_path).write_bytes(
            b"".join(Path(path).read_bytes() for path in video_paths)
        )


class BrokenMerger:
    def merge_paths(self, video_paths: list[str], output_path: str) -> None:
        raise RuntimeError("ffmpeg failed")


class FakeValidator:
    def validate_path(self, path, *, original_filename, mime_type=None):
        return ValidatedRemakeMedia(
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
            duration_seconds=8.0,
            width=1080,
            height=1920,
            container_format="mp4",
            checksum="b" * 64,
        )


class LocalProvider:
    enabled = False
    name = "local"


class MemoryOssProvider:
    enabled = True
    name = "aliyun"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def normalize_media_ref(self, raw):
        return raw

    async def download_to_file(self, key, destination):
        destination.write_bytes(self.objects[key])

    async def put_file(self, key, source, content_type):
        self.objects[key] = source.read_bytes()

    async def delete(self, key):
        self.objects.pop(key, None)


class PartialFailureOssProvider(MemoryOssProvider):
    async def put_file(self, key, source, content_type):
        self.objects[key] = b"partial"
        raise RuntimeError("network interrupted")


async def create_history_chapter(media_root: Path) -> tuple[Novel, Chapter, list[Path]]:
    novel = await Novel.create(name="旧项目", author="作者", team_id=3)
    chapter = await Chapter.create(
        novel=novel,
        number=4,
        name="第4集",
        content="",
    )
    source_paths: list[Path] = []
    for sequence, payload in ((1, b"first"), (2, b"second")):
        path = media_root / "videos" / f"shot-{sequence}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        source_paths.append(path)
        scene = await Scene.create(
            chapter=chapter,
            sequence=sequence,
            prompt="镜头",
            duration=4,
        )
        video = await Video.create(
            scene=scene,
            model_type=VideoModelTypeEnum.seedance.value,
            status=TaskStatusEnum.completed.value,
            url=f"/media/videos/{path.name}",
            metadata={"size_bytes": len(payload)},
        )
        scene.metadata = {"workbench": {"activeVideoId": video.id}}
        await scene.save(update_fields=["metadata", "updated_at"])
    return novel, chapter, source_paths


@pytest.mark.asyncio
async def test_snapshot_is_ordered_and_independent_from_source_project(tmp_path):
    novel, chapter, source_paths = await create_history_chapter(tmp_path)
    service = RemakeHistorySnapshotService(
        catalog=RemakeHistoryCatalog(),
        merger=FakeMerger(),
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )

    snapshot = await service.create(chapter, team_id=3)
    snapshot_path = tmp_path / snapshot.object_key

    assert snapshot.storage_provider == "local"
    assert snapshot_path.read_bytes() == b"firstsecond"
    assert snapshot.manifest["source_novel_id"] == novel.id
    assert snapshot.manifest["source_chapter_id"] == chapter.id
    assert [item["sequence"] for item in snapshot.manifest["components"]] == [1, 2]
    assert len({item["video_id"] for item in snapshot.manifest["components"]}) == 2

    source_paths[0].write_bytes(b"changed")
    await novel.delete()
    assert snapshot_path.read_bytes() == b"firstsecond"


@pytest.mark.asyncio
async def test_snapshot_rejects_unavailable_episode(tmp_path):
    novel = await Novel.create(name="未完成旧项目", author="作者")
    chapter = await Chapter.create(novel=novel, number=1, name="第1集", content="")
    service = RemakeHistorySnapshotService(
        catalog=RemakeHistoryCatalog(),
        merger=FakeMerger(),
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )

    with pytest.raises(RemakeError) as caught:
        await service.create(chapter, team_id=None)

    assert caught.value.error_code == "REMAKE_HISTORY_EPISODE_UNAVAILABLE"
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_snapshot_wraps_merge_failure_and_cleans_partial_files(tmp_path):
    _, chapter, _ = await create_history_chapter(tmp_path)
    service = RemakeHistorySnapshotService(
        catalog=RemakeHistoryCatalog(),
        merger=BrokenMerger(),
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )

    with pytest.raises(RemakeError) as caught:
        await service.create(chapter, team_id=3)

    assert caught.value.error_code == "REMAKE_HISTORY_SNAPSHOT_FAILED"
    assert caught.value.status_code == 500
    assert caught.value.retryable is True
    assert not list((tmp_path / "remake" / "sources" / "history").glob("*.mp4"))


@pytest.mark.asyncio
async def test_snapshot_uses_normalized_oss_storage_kind(tmp_path):
    _, chapter, _ = await create_history_chapter(tmp_path)
    provider = MemoryOssProvider()
    service = RemakeHistorySnapshotService(
        catalog=RemakeHistoryCatalog(),
        merger=FakeMerger(),
        validator=FakeValidator(),
        provider=provider,
        media_root=tmp_path,
    )

    snapshot = await service.create(chapter, team_id=3)

    assert snapshot.storage_provider == "oss"
    assert provider.objects[snapshot.object_key] == b"firstsecond"
    await service.cleanup(snapshot)
    assert snapshot.object_key not in provider.objects


@pytest.mark.asyncio
async def test_snapshot_removes_partial_oss_object_after_upload_failure(tmp_path):
    _, chapter, _ = await create_history_chapter(tmp_path)
    provider = PartialFailureOssProvider()
    service = RemakeHistorySnapshotService(
        catalog=RemakeHistoryCatalog(),
        merger=FakeMerger(),
        validator=FakeValidator(),
        provider=provider,
        media_root=tmp_path,
    )

    with pytest.raises(RemakeError) as caught:
        await service.create(chapter, team_id=3)

    assert caught.value.error_code == "REMAKE_HISTORY_SNAPSHOT_FAILED"
    assert provider.objects == {}
