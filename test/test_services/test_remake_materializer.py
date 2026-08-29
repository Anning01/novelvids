from pathlib import Path

import pytest

from services.remake.materializer import RemakeMediaMaterializer, RemakeMaterializationError


class _Source:
    storage_provider = "local"
    object_key = "remake/sources/source.mp4"
    original_filename = "source.mp4"


class _Provider:
    enabled = True

    def __init__(self):
        self.calls = []

    async def download_to_file(self, key, destination):
        self.calls.append((key, destination))
        destination.write_bytes(b"oss-video")


@pytest.mark.asyncio
async def test_local_materializer_resolves_only_file_inside_media_root(tmp_path: Path):
    source_path = tmp_path / _Source.object_key
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"video")
    service = RemakeMediaMaterializer(media_root=tmp_path, provider=_Provider())

    assert await service.materialize(_Source(), tmp_path / "work") == source_path.resolve()

    outside = _Source()
    outside.object_key = "../secret.mp4"
    with pytest.raises(RemakeMaterializationError, match="越界"):
        await service.materialize(outside, tmp_path / "work")


@pytest.mark.asyncio
async def test_oss_materializer_streams_controlled_object_to_task_directory(tmp_path: Path):
    provider = _Provider()
    source = _Source()
    source.storage_provider = "oss"
    source.object_key = "remake/sources/remote.mov"
    source.original_filename = "远程.mov"
    service = RemakeMediaMaterializer(media_root=tmp_path, provider=provider)

    result = await service.materialize(source, tmp_path / "work")

    assert result.read_bytes() == b"oss-video"
    assert result.suffix == ".mov"
    assert provider.calls == [("remake/sources/remote.mov", result)]


@pytest.mark.asyncio
async def test_materializer_rejects_unknown_storage_provider(tmp_path: Path):
    source = _Source()
    source.storage_provider = "external"
    service = RemakeMediaMaterializer(media_root=tmp_path, provider=_Provider())

    with pytest.raises(RemakeMaterializationError, match="不支持的来源存储类型"):
        await service.materialize(source, tmp_path / "work")
