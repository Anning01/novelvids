from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from models.video import Video
from services.remake.media import ValidatedRemakeMedia
from services.remake.history import RemakeHistoryCatalog
from services.remake.history_snapshot import RemakeHistorySnapshotService
from services.remake.projects import RemakeProjectService
from services.remake.uploads import RemakeUploadService
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, VideoModelTypeEnum


class FakeValidator:
    def validate_extension(self, filename: str) -> None:
        if Path(filename).suffix.lower() not in {".mp4", ".mov"}:
            from exceptions.remake import RemakeError

            raise RemakeError(
                422,
                "REMAKE_MEDIA_EXTENSION_UNSUPPORTED",
                "来源视频仅支持 MP4 或 MOV 格式",
            )

    def validate_path(self, path, *, original_filename, mime_type=None):
        return ValidatedRemakeMedia(
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
            duration_seconds=18.25,
            width=1080,
            height=1920,
            container_format=Path(original_filename).suffix.lower().lstrip("."),
            checksum="a" * 64,
        )


class LocalProvider:
    enabled = False
    name = "local"


class OssProvider:
    enabled = True
    name = "aliyun"

    def __init__(self, payload: bytes = b"oss-video") -> None:
        self.payload = payload
        self.deleted: list[str] = []

    def sign_form_upload(self, key, content_type, max_size):
        return {
            "url": "https://upload.example.test",
            "fields": {
                "key": key,
                "Content-Type": content_type,
                "policy": "signed",
            },
        }

    async def download_to_file(self, key, destination):
        destination.write_bytes(self.payload)

    async def delete(self, key):
        self.deleted.append(key)


class FakeMerger:
    def merge_paths(self, video_paths, output_path):
        Path(output_path).write_bytes(
            b"".join(Path(path).read_bytes() for path in video_paths)
        )


def install_services(monkeypatch, tmp_path, provider):
    import api.remake as remake_api

    upload_service = RemakeUploadService(
        validator=FakeValidator(),
        provider=provider,
        media_root=tmp_path,
    )
    project_service = RemakeProjectService(upload_service=upload_service)
    monkeypatch.setattr(remake_api, "remake_upload_service", upload_service)
    monkeypatch.setattr(remake_api, "remake_project_service", project_service)
    return upload_service


@pytest.mark.asyncio
async def test_capabilities_are_backend_managed(client):
    response = await client.get("/api/remake/capabilities")
    body = response.json()

    assert body["code"] == 0
    assert body["data"]["media"] == {
        "extensions": ["mp4", "mov"],
        "max_bytes": 500 * 1024 * 1024,
        "max_duration_seconds": 1200,
    }
    assert "9:16" in body["data"]["aspect_ratios"]
    assert "720p" in body["data"]["resolutions"]
    assert body["data"]["styles"][0] == {
        "key": "auto",
        "label": "AI 识别风格",
    }
    assert {"key": "realistic-general", "label": "写实通用"} in body["data"]["styles"]
    assert body["data"]["source_modes"]["single_upload"] is True
    assert body["data"]["source_modes"]["history"] is True
    assert body["data"]["source_modes"]["folder_upload"] is True
    assert body["data"]["episode_patterns"] == [
        "第12集", "第12话", "EP12", "E12", "12集"
    ]


@pytest.mark.asyncio
async def test_history_catalog_and_episode_availability_are_exposed(client):
    novel = await Novel.create(name="可重制历史项目", author="作者")
    ready = await Chapter.create(
        novel=novel,
        number=1,
        name="第1集",
        content="",
    )
    ready_scene = await Scene.create(
        chapter=ready,
        sequence=1,
        prompt="镜头",
        duration=5,
    )
    ready_video = await Video.create(
        scene=ready_scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/ready.mp4",
        metadata={"size_bytes": 1024},
    )
    ready_scene.metadata = {"workbench": {"activeVideoId": ready_video.id}}
    await ready_scene.save(update_fields=["metadata", "updated_at"])

    pending = await Chapter.create(
        novel=novel,
        number=2,
        name="第2集",
        content="",
    )
    await Scene.create(chapter=pending, sequence=1, prompt="镜头", duration=5)

    projects = await client.get(
        "/api/remake/history/projects",
        params={"keyword": "历史", "page": 1, "page_size": 10},
    )
    project_data = projects.json()["data"]
    assert project_data["items"] == [{
        "id": novel.id,
        "name": novel.name,
        "cover": None,
        "available_episode_count": 1,
    }]
    assert project_data["pagination"]["total"] == 1

    episodes = await client.get(
        f"/api/remake/history/projects/{novel.id}/episodes"
    )
    episode_data = episodes.json()["data"]
    assert episode_data[0]["available"] is True
    assert episode_data[1]["available"] is False
    assert "已完成视频" in episode_data[1]["unavailable_reason"]


@pytest.mark.asyncio
async def test_remake_projects_cannot_be_reused_as_history_sources(client):
    remake = await Novel.create(
        name="已经重制的项目",
        author="作者",
        workflow_kind="remake",
    )
    chapter = await Chapter.create(
        novel=remake,
        number=1,
        name="第1集",
        content="",
    )

    episodes = await client.get(
        f"/api/remake/history/projects/{remake.id}/episodes"
    )
    assert episodes.json()["code"] == 404
    assert episodes.json()["data"]["error_code"] == "REMAKE_HISTORY_PROJECT_NOT_FOUND"

    created = await client.post(
        "/api/remake/projects",
        json={
            "name": "禁止二次套娃",
            "source_mode": "history",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "style_key": None,
            "custom_style_prompt": None,
            "idempotency_key": "01916f1a-41aa-7000-8000-000000000103",
            "sources": [{"source_chapter_id": chapter.id}],
        },
    )
    assert created.json()["code"] == 422
    assert created.json()["data"]["error_code"] == "REMAKE_HISTORY_EPISODE_UNAVAILABLE"
    assert "短剧制作" in created.json()["message"]


@pytest.mark.asyncio
async def test_history_episode_can_create_project_from_immutable_snapshot(
    client, monkeypatch, tmp_path
):
    import api.remake as remake_api

    novel = await Novel.create(name="待快照旧项目", author="作者")
    chapter = await Chapter.create(
        novel=novel,
        number=3,
        name="第3集",
        content="",
    )
    source_path = tmp_path / "videos" / "old.mp4"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"old-version")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="镜头", duration=5)
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/old.mp4",
        metadata={"size_bytes": source_path.stat().st_size},
    )
    scene.metadata = {"workbench": {"activeVideoId": video.id}}
    await scene.save(update_fields=["metadata", "updated_at"])

    snapshot_service = RemakeHistorySnapshotService(
        catalog=RemakeHistoryCatalog(),
        merger=FakeMerger(),
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    project_service = RemakeProjectService(
        history_snapshot_service=snapshot_service
    )
    monkeypatch.setattr(remake_api, "remake_project_service", project_service)
    run = AsyncMock()
    monkeypatch.setattr(remake_api.ai_task_executor, "run", run)

    created = await client.post(
        "/api/remake/projects",
        json={
            "name": "API 历史重制",
            "source_mode": "history",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "style_key": "realistic-general",
            "custom_style_prompt": None,
            "idempotency_key": "01916f1a-41aa-7000-8000-000000000003",
            "sources": [{"source_chapter_id": chapter.id}],
        },
    )

    assert created.json()["code"] == 0, created.text
    source = await RemakeSource.get(
        id=created.json()["data"]["sources"][0]["source_id"]
    )
    snapshot_path = tmp_path / source.object_key
    assert source.source_kind == "history"
    assert source.source_novel_id == novel.id
    assert source.source_chapter_id == chapter.id
    assert snapshot_path.read_bytes() == b"old-version"

    source_path.write_bytes(b"new-version")
    await novel.delete()
    assert snapshot_path.read_bytes() == b"old-version"


@pytest.mark.asyncio
async def test_local_upload_rejects_bad_extension_with_stable_error(
    client, monkeypatch, tmp_path
):
    install_services(monkeypatch, tmp_path, LocalProvider())

    response = await client.post(
        "/api/remake/uploads",
        files={"file": ("demo.avi", BytesIO(b"video"), "video/x-msvideo")},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["code"] == 422
    assert body["data"]["error_code"] == "REMAKE_MEDIA_EXTENSION_UNSUPPORTED"
    assert "traceback" not in response.text.lower()


@pytest.mark.asyncio
async def test_local_upload_create_project_and_read_sources(
    client, monkeypatch, tmp_path
):
    install_services(monkeypatch, tmp_path, LocalProvider())

    uploaded = await client.post(
        "/api/remake/uploads",
        files={"file": ("第1集.mp4", BytesIO(b"video"), "video/mp4")},
    )
    upload_data = uploaded.json()["data"]
    assert upload_data["status"] == "ready"
    assert upload_data["duration_seconds"] == 18.25

    created = await client.post(
        "/api/remake/projects",
        json={
            "name": "API 单视频重制",
            "source_mode": "single_upload",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "style_key": "realistic-general",
            "custom_style_prompt": None,
            "idempotency_key": "01916f1a-41aa-7000-8000-000000000001",
            "sources": [
                {"episode_number": 1, "upload_token": upload_data["upload_token"]}
            ],
        },
    )
    created_body = created.json()
    assert created_body["code"] == 0
    novel_id = created_body["data"]["novel_id"]
    assert created_body["data"]["entry_path"] == f"/create/remake/{novel_id}/progress"

    project = (await client.get(f"/api/remake/projects/{novel_id}")).json()
    assert project["data"]["workflow_kind"] == "remake"
    assert project["data"]["aspect_ratio"] == "9:16"

    sources = (await client.get(f"/api/remake/projects/{novel_id}/sources")).json()
    assert len(sources["data"]) == 1
    assert sources["data"][0]["episode_number"] == 1
    assert sources["data"][0]["original_filename"] == "第1集.mp4"


@pytest.mark.asyncio
async def test_completed_project_progress_is_available_as_snapshot_and_sse(client):
    novel = await Novel.create(
        name="SSE 重制项目",
        author="重制工坊",
        workflow_kind="remake",
    )
    chapter = await Chapter.create(
        novel=novel,
        number=1,
        name="第1集",
        content="",
    )
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.completed.value,
        stage="completed",
        progress=100,
    )
    await RemakeSource.create(
        novel=novel,
        chapter=chapter,
        episode_number=1,
        source_kind="upload",
        storage_provider="local",
        object_key="remake/sse.mp4",
        original_filename="第1集.mp4",
        mime_type="video/mp4",
        size_bytes=1024,
        duration_seconds=12,
        width=1080,
        height=1920,
        container_format="mp4",
        checksum="a" * 64,
        media_status="completed",
        analysis_task=task,
    )

    snapshot = await client.get(f"/api/remake/projects/{novel.id}/progress")
    assert snapshot.json()["data"]["aggregate_status"] == "completed"

    events = await client.get(f"/api/remake/projects/{novel.id}/events")
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: complete" in events.text
    assert '"overall_progress":100' in events.text


@pytest.mark.asyncio
async def test_oss_policy_finalize_and_release(client, monkeypatch, tmp_path):
    provider = OssProvider()
    install_services(monkeypatch, tmp_path, provider)

    policy = await client.get(
        "/api/remake/uploads/policy",
        params={
            "filename": "第1集.mov",
            "content_type": "video/quicktime",
            "size_bytes": len(provider.payload),
        },
    )
    policy_data = policy.json()["data"]
    assert policy_data["direct"] is True
    assert policy_data["upload_url"] == "https://upload.example.test"
    assert policy_data["fields"]["key"] == policy_data["object_key"]

    finalized = await client.post(
        "/api/remake/uploads/finalize",
        json={
            "object_key": policy_data["object_key"],
            "original_filename": "第1集.mov",
        },
    )
    upload_data = finalized.json()["data"]
    assert upload_data["status"] == "ready"

    released = await client.delete(
        f"/api/remake/uploads/{upload_data['upload_token']}"
    )
    assert released.json()["code"] == 0
    assert provider.deleted == [policy_data["object_key"]]


@pytest.mark.asyncio
async def test_oss_upload_project_normalizes_source_storage_provider(
    client, monkeypatch, tmp_path
):
    provider = OssProvider()
    install_services(monkeypatch, tmp_path, provider)
    policy = (
        await client.get(
            "/api/remake/uploads/policy",
            params={
                "filename": "第1集.mp4",
                "content_type": "video/mp4",
                "size_bytes": len(provider.payload),
            },
        )
    ).json()["data"]
    upload = (
        await client.post(
            "/api/remake/uploads/finalize",
            json={
                "object_key": policy["object_key"],
                "original_filename": "第1集.mp4",
            },
        )
    ).json()["data"]

    created = await client.post(
        "/api/remake/projects",
        json={
            "name": "OSS 单视频重制",
            "source_mode": "single_upload",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "style_key": "realistic-general",
            "custom_style_prompt": None,
            "idempotency_key": "01916f1a-41aa-7000-8000-000000000004",
            "sources": [{"episode_number": 1, "upload_token": upload["upload_token"]}],
        },
    )

    source = await RemakeSource.get(
        id=created.json()["data"]["sources"][0]["source_id"]
    )
    assert source.storage_provider == "oss"


@pytest.mark.asyncio
async def test_folder_upload_creates_sorted_chapters_and_dispatches_each_task(
    client, monkeypatch, tmp_path
):
    import api.remake as remake_api

    install_services(monkeypatch, tmp_path, LocalProvider())
    run = AsyncMock()
    monkeypatch.setattr(remake_api.ai_task_executor, "run", run)
    uploads = {}
    for filename in ("第3集.mp4", "EP01.mov", "第2话.mp4"):
        response = await client.post(
            "/api/remake/uploads",
            files={"file": (filename, BytesIO(b"video"), "video/mp4")},
        )
        uploads[filename] = response.json()["data"]["upload_token"]

    created = await client.post(
        "/api/remake/projects",
        json={
            "name": "API 文件夹重制",
            "source_mode": "folder_upload",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "style_key": "realistic-general",
            "custom_style_prompt": None,
            "idempotency_key": "01916f1a-41aa-7000-8000-000000000005",
            "sources": [
                {"episode_number": 3, "upload_token": uploads["第3集.mp4"]},
                {"episode_number": 1, "upload_token": uploads["EP01.mov"]},
                {"episode_number": 2, "upload_token": uploads["第2话.mp4"]},
            ],
        },
    )

    assert created.json()["code"] == 0, created.text
    data = created.json()["data"]
    assert [item["episode_number"] for item in data["sources"]] == [1, 2, 3]
    assert await Chapter.filter(novel_id=data["novel_id"]).count() == 3
    assert run.await_count == 3

    project = (
        await client.get(f"/api/remake/projects/{data['novel_id']}")
    ).json()["data"]
    assert project["aggregate_status"] == "queued"
    assert project["source_summary"] == {
        "total": 3,
        "queued": 3,
        "processing": 0,
        "completed": 0,
        "failed": 0,
    }

    tasks = [await AiTask.get(id=item["task_id"]) for item in data["sources"]]
    tasks[0].status = TaskStatusEnum.completed.value
    tasks[1].status = TaskStatusEnum.failed.value
    tasks[2].status = TaskStatusEnum.running.value
    for task in tasks:
        await task.save(update_fields=["status", "updated_at"])
    partial = (
        await client.get(f"/api/remake/projects/{data['novel_id']}")
    ).json()["data"]
    assert partial["aggregate_status"] == "partial_failed"
    assert partial["source_summary"]["completed"] == 1
    assert partial["source_summary"]["failed"] == 1
    assert partial["source_summary"]["processing"] == 1


@pytest.mark.asyncio
async def test_create_dispatches_background_decomposition_and_failed_source_can_retry(
    client, monkeypatch, tmp_path
):
    import api.remake as remake_api

    install_services(monkeypatch, tmp_path, LocalProvider())
    run = AsyncMock()
    monkeypatch.setattr(remake_api.ai_task_executor, "run", run)
    uploaded = await client.post(
        "/api/remake/uploads",
        files={"file": ("第1集.mp4", BytesIO(b"video"), "video/mp4")},
    )
    upload_token = uploaded.json()["data"]["upload_token"]

    created = await client.post(
        "/api/remake/projects",
        json={
            "name": "后台拆解 API",
            "source_mode": "single_upload",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "style_key": "realistic-general",
            "custom_style_prompt": None,
            "idempotency_key": "01916f1a-41aa-7000-8000-000000000002",
            "sources": [{"episode_number": 1, "upload_token": upload_token}],
        },
    )

    assert created.json()["code"] == 0
    first_task = run.await_args.args[0]
    source = await RemakeSource.get(id=created.json()["data"]["sources"][0]["source_id"])
    first_task.status = TaskStatusEnum.failed.value
    await first_task.save(update_fields=["status", "updated_at"])
    source.media_status = "failed"
    await source.save(update_fields=["media_status", "updated_at"])

    retried = await client.post(
        f"/api/remake/projects/{source.novel_id}/sources/{source.id}/retry"
    )

    assert retried.json()["code"] == 0
    assert run.await_count == 2
    second_task = run.await_args.args[0]
    assert second_task.id != first_task.id
    assert second_task.request_params["attempt"] == 2
    assert await AiTask.filter(id=second_task.id).exists()
