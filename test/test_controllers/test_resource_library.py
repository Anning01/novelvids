import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from tortoise import Tortoise

from auth.deps import AuthContext, get_auth_context
from config import settings
from controllers.resource_library import resource_for, resource_library_controller as library, validate_resource_model
from main import app
from models.resource_library import ResourceFolder, VideoResource
from schemas.resource_library import FolderWrite
from schemas.video import VideoReferenceMedia
from services.oss.base import LocalProvider
from services.resource_storage import resource_storage
from services.video.capabilities import capabilities_for
from services.video.reference_media import render_reference_mentions, select_referenced_media


@pytest.fixture(autouse=True)
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    monkeypatch.setattr("services.resource_storage.oss", LocalProvider())
    monkeypatch.setattr("api.resource_library.oss", LocalProvider())


@pytest.fixture
async def clip(tmp_path):
    path = tmp_path / "clip.mp4"
    await asyncio.to_thread(subprocess.run, [
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1280x720:r=24:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True)
    return path


async def folder(team=0, name="角色", parent_id=0):
    return await library.write_folder(team, None, FolderWrite(name=name, parent_id=parent_id))


async def ready(team=0, folder_id=0):
    resource = await library.reserve(team, None, "clip.mp4", folder_id)
    resource.state = "ready"
    await resource.save()
    return resource


@pytest.mark.asyncio
async def test_two_levels_and_illegal_folder_moves():
    root = await folder()
    child = await folder(name="二级", parent_id=root.id)
    with pytest.raises(HTTPException):
        await folder(name="三级", parent_id=child.id)
    for destination in (root.id, child.id):
        with pytest.raises(HTTPException):
            await library.write_folder(0, None, FolderWrite(name=root.name, parent_id=destination), root.id)
    other = await folder(name="其他")
    with pytest.raises(HTTPException):
        await library.write_folder(0, None, FolderWrite(name=root.name, parent_id=other.id), root.id)
    moved = await library.write_folder(0, None, FolderWrite(name=child.name, parent_id=other.id), child.id)
    assert moved.parent_id == other.id


@pytest.mark.asyncio
async def test_sibling_names_unique_but_other_scopes_allowed():
    await folder()
    with pytest.raises(HTTPException, match="同名"):
        await folder()
    await folder(team=2)
    parent = await folder(name="上级")
    await folder(parent_id=parent.id)


@pytest.mark.asyncio
async def test_folder_name_validation_and_foreign_parent():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        FolderWrite(name=" ../ ")
    foreign = await folder(team=2)
    with pytest.raises(HTTPException):
        await folder(parent_id=foreign.id)


@pytest.mark.asyncio
async def test_bulk_move_atomic_and_stable_reference():
    target = await folder()
    first = await ready()
    foreign = await ready(team=2)
    with pytest.raises(HTTPException):
        await library.move(0, [first.id, foreign.id], target.id)
    await first.refresh_from_db()
    assert first.folder_id == 0
    storage_ref = first.storage_ref
    await library.move(0, [first.id], target.id)
    await first.refresh_from_db()
    assert first.folder_id == target.id
    assert first.storage_ref == storage_ref
    await library.move(0, [first.id], 0)


@pytest.mark.asyncio
async def test_resource_scope_and_deletion_state_block_new_references():
    resource = await ready(team=1)
    with pytest.raises(HTTPException):
        await resource_for(2, resource.id)
    resource.state = "delete_failed"
    await resource.save()
    with pytest.raises(HTTPException):
        await resource_for(1, resource.id)


@pytest.mark.asyncio
async def test_storage_cleanup_failure_is_retryable(monkeypatch):
    resource = await ready()
    resource.poster_ref = resource.storage_ref + ".poster.jpg"
    await resource.save()
    delete = AsyncMock(side_effect=[None, RuntimeError("storage unavailable")])
    monkeypatch.setattr(resource_storage, "delete", delete)
    results = await library.delete_resources(0, [resource.id])
    assert results == [{"id": resource.id, "deleted": False, "error": "存储文件删除失败，请重试"}]
    await resource.refresh_from_db()
    assert resource.state == "delete_failed"
    with pytest.raises(HTTPException):
        await resource_for(0, resource.id)
    monkeypatch.setattr(resource_storage, "delete", AsyncMock())
    assert (await library.delete_resources(0, [resource.id]))[0]["deleted"]
    assert (await library.delete_resources(0, [resource.id]))[0]["deleted"]


@pytest.mark.asyncio
async def test_folder_cascade_retains_failed_directories(monkeypatch):
    root = await folder()
    child = await folder(name="二级", parent_id=root.id)
    resource = await ready(folder_id=child.id)
    foreign = await ready(team=2)
    monkeypatch.setattr(resource_storage, "delete", AsyncMock(side_effect=RuntimeError()))
    result = await library.delete_folder(0, root.id)
    assert not result[0]["deleted"]
    assert await ResourceFolder.filter(id=root.id, deleting=True).exists()
    assert await ResourceFolder.filter(id=child.id).exists()
    with pytest.raises(HTTPException):
        await library.reserve(0, None, "a.mp4", child.id)
    monkeypatch.setattr(resource_storage, "delete", AsyncMock())
    await library.delete_folder(0, root.id)
    assert not await ResourceFolder.filter(id__in=[root.id, child.id]).exists()
    assert not await VideoResource.filter(id=resource.id).exists()
    assert await VideoResource.filter(id=foreign.id).exists()


@pytest.mark.asyncio
async def test_upload_validates_actual_file_and_generates_poster(client, clip):
    target = await folder()
    response = await client.post("/api/resource-library/upload", data={"folder_id": target.id}, files={"file": ("demo.mp4", clip.read_bytes(), "video/mp4")})
    assert response.json()["code"] == 0, response.text
    resource = response.json()["data"]
    assert resource["folder_id"] == target.id
    assert resource["width"] == 1280
    assert resource["duration"] == 2
    assert Path(resource_storage.local_path(resource["poster_url"])).is_file()
    stored = await resource_for(0, resource["id"])
    validate_resource_model(stored, capabilities_for("seedance_2"))
    from models.config import AiModelConfig
    from utils.enums import AiTaskTypeEnum
    config = await AiModelConfig.create(task_type=AiTaskTypeEnum.video.value, name="video", base_url="https://example.invalid", api_key="", model="test", api_protocol="volcengine_ark", video_model_type="seedance_2", is_active=True)
    response = await client.post("/api/resource-library/selection", json={"ids": [stored.id], "model_config_id": config.id})
    assert response.json()["code"] == 0, response.text
    selected = VideoReferenceMedia(**response.json()["data"][0])
    assert selected.library_resource_id == stored.id
    assert selected.duration == 2
    stored.media["_probe"]["format"]["duration"] = "999"
    with pytest.raises(HTTPException):
        validate_resource_model(stored, capabilities_for("seedance_2"))


@pytest.mark.asyncio
async def test_invalid_upload_removed_and_size_limit(client, monkeypatch):
    response = await client.post("/api/resource-library/upload", files={"file": ("fake.mp4", b"not a video", "video/mp4")})
    assert response.json()["code"] != 0
    assert not await VideoResource.all().exists()
    monkeypatch.setattr(settings, "RESOURCE_LIBRARY_MAX_SIZE_MB", 1)
    response = await client.post("/api/resource-library/upload", files={"file": ("big.mp4", b"x" * (1024 * 1024 + 1), "video/mp4")})
    assert response.json()["code"] == 400
    assert not await VideoResource.all().exists()
    response = await client.post("/api/resource-library/upload", files={"file": ("fake.png", b"x", "image/png")})
    assert response.json()["code"] == 400


@pytest.mark.asyncio
async def test_source_upload_hidden_and_import_is_independent(client, clip):
    uploaded = await client.post("/api/resource-library/upload", data={"source": "true"}, files={"file": ("demo.mp4", clip.read_bytes(), "video/mp4")})
    source = uploaded.json()["data"]
    listing = await client.get("/api/resource-library/resources")
    assert listing.json()["data"]["items"] == []
    imported = await client.post("/api/resource-library/import", json={"source": "upload", "source_id": source["id"], "name": "收藏"})
    assert imported.json()["code"] == 0, imported.text
    resource = imported.json()["data"]
    assert resource["storage_ref"] != source["storage_ref"]
    response = await client.post("/api/resource-library/delete", json={"ids": [resource["id"]]})
    assert response.json()["data"][0]["deleted"]
    assert resource_storage.local_path(source["storage_ref"]).is_file()
    assert not resource_storage.local_path(resource["storage_ref"]).exists()


@pytest.mark.asyncio
async def test_import_rejects_foreign_or_arbitrary_source(client):
    source = await VideoResource.create(team_id=2, state="source", name="private", filename="p.mp4", storage_ref="/media/private.mp4")
    response = await client.post("/api/resource-library/import", json={"source": "upload", "source_id": source.id, "name": "stolen"})
    assert response.json()["code"] == 404
    response = await client.post("/api/resource-library/import", json={"source": "url", "source_id": 1, "media_url": "https://example.com/a.mp4", "name": "remote"})
    assert response.json()["code"] == 422


@pytest.mark.asyncio
async def test_search_crosses_folders_but_not_teams(client):
    target = await folder()
    a = await ready(folder_id=target.id)
    await ready(team=2)
    response = await client.get("/api/resource-library/resources", params={"folder_id": 0, "search": "clip"})
    assert [item["id"] for item in response.json()["data"]["items"]] == [a.id]


@pytest.mark.asyncio
async def test_oss_ticket_uses_reserved_key_and_finalizes_idempotently(client, clip, monkeypatch):
    class Storage:
        enabled = True
        def sign_form_upload(self, key, mime, size):
            assert key.startswith("uploads/0/")
            return {"url": "https://storage.invalid", "fields": {"key": key}}
        async def download_to_file(self, key, destination):
            destination.write_bytes(clip.read_bytes())
        async def put_file(self, key, path, mime):
            pass
        def resolve_url(self, key):
            return key
    storage = Storage()
    monkeypatch.setattr("api.resource_library.oss", storage)
    monkeypatch.setattr("services.resource_storage.oss", storage)
    response = await client.post("/api/resource-library/upload-policy", json={"filename": "a.mp4"})
    ticket = response.json()["data"]
    assert ticket["direct"]
    response = await client.post(f'/api/resource-library/resources/{ticket["resource_id"]}/finalize')
    assert response.json()["code"] == 0, response.text
    response = await client.post(f'/api/resource-library/resources/{ticket["resource_id"]}/finalize')
    assert response.json()["data"]["state"] == "ready"


@pytest.mark.asyncio
async def test_safe_schema_repeated_start_preserves_resources():
    resource = await ready()
    await Tortoise.generate_schemas(safe=True)
    await Tortoise.generate_schemas(safe=True)
    assert (await resource_for(0, resource.id)).name == resource.name


def test_canvas_mentions_and_legacy_references():
    resource = VideoReferenceMedia(type="video", url="/media/a.mp4", library_resource_id=1, mention_name="动作参考", name="动作")
    prompt = "根据 @{动作参考} 运动"
    assert select_referenced_media(prompt, [resource]) == [resource]
    assert "【参考视频：动作】" in render_reference_mentions(prompt, [resource])
    assert select_referenced_media("无引用", [resource]) == []
    legacy = VideoReferenceMedia(type="video", url="x.mp4")
    assert select_referenced_media("@{参考视频:x.mp4}", [legacy]) == [legacy]


@pytest.mark.asyncio
@pytest.mark.parametrize("role,can_write", [("admin", True), ("creator", True), ("viewer", False)])
async def test_roles_and_active_team_scope(client, monkeypatch, role, can_write):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    ctx = AuthContext(user=SimpleNamespace(id=5), membership=SimpleNamespace(role=role), team_id=7)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    try:
        foreign = await folder(team=8)
        response = await client.post("/api/resource-library/folders", json={"name": "共同目录"})
        assert response.json()["code"] == (0 if can_write else 403)
        listing = await client.get("/api/resource-library/folders")
        assert all(item["id"] != foreign.id for item in listing.json()["data"])
        response = await client.put(f"/api/resource-library/folders/{foreign.id}", json={"name": "越权"})
        assert response.json()["code"] in {403, 404}
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


@pytest.mark.asyncio
async def test_super_admin_requires_explicit_team(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=SimpleNamespace(id=1), is_super_admin=True)
    try:
        response = await client.get("/api/resource-library/folders")
        assert response.json()["code"] == 400
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


@pytest.mark.asyncio
async def test_folder_resource_endpoints_and_delete_preview(client):
    root = (await client.post("/api/resource-library/folders", json={"name": "根目录"})).json()["data"]
    child = (await client.post("/api/resource-library/folders", json={"name": "子目录", "parent_id": root["id"]})).json()["data"]
    resource = await ready(folder_id=child["id"])
    response = await client.put(f'/api/resource-library/folders/{child["id"]}', json={"name": "改名", "parent_id": root["id"]})
    assert response.json()["data"]["name"] == "改名"
    response = await client.patch(f"/api/resource-library/resources/{resource.id}", json={"name": "新名称"})
    assert response.json()["data"]["name"] == "新名称"
    assert (await client.get(f"/api/resource-library/resources/{resource.id}")).json()["data"]["name"] == "新名称"
    preview = (await client.get(f'/api/resource-library/folders/{root["id"]}/delete-preview')).json()["data"]
    assert preview == {"folder_count": 2, "resource_count": 1}
    response = await client.post("/api/resource-library/move", json={"ids": [resource.id, resource.id], "folder_id": 0})
    assert response.json()["code"] == 0
    await resource.refresh_from_db()
    assert resource.folder_id == 0
    response = await client.delete(f'/api/resource-library/folders/{root["id"]}')
    assert response.json()["code"] == 0
    assert not await ResourceFolder.all().exists()
    assert (await client.get("/api/resource-library/capabilities")).json()["data"]["folder_depth"] == 2


@pytest.mark.asyncio
async def test_library_reference_generation_validates_identity_before_submission(client, clip, monkeypatch):
    from controllers.video import video_controller
    from models.novel import Novel
    from models.chapter import Chapter
    from models.scene import Scene
    from models.config import AiModelConfig
    from schemas.video import VideoGenerateRequest
    from utils.enums import AiTaskTypeEnum
    source = (await client.post("/api/resource-library/upload", files={"file": ("clip.mp4", clip.read_bytes(), "video/mp4")})).json()["data"]
    novel = await Novel.create(name="Library generation", author="test")
    chapter = await Chapter.create(novel=novel, number=1, name="one", content="test")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="模仿 @{动作参考}", duration=6)
    config = await AiModelConfig.create(task_type=AiTaskTypeEnum.video.value, name="video", base_url="https://provider.invalid", api_key="", model="test", api_protocol="volcengine_ark", video_model_type="seedance_2", is_active=True)
    req = VideoGenerateRequest(scene_id=scene.id, model_config_id=config.id, reference_media=[VideoReferenceMedia(
        type="video", url="https://untrusted.invalid/forged.mp4", library_resource_id=source["id"], mention_name="动作参考", duration=999,
    )])
    generator = AsyncMock()
    generator.submit.return_value = "library-task"
    monkeypatch.setattr("controllers.video.get_generator", lambda config: generator)
    result = await video_controller.generate(req, media_base_url="https://app.invalid")
    assert result.metadata["reference_media"][0]["url"] == source["storage_ref"]
    assert result.metadata["reference_media"][0]["duration"] == 2
    submitted = generator.submit.call_args
    assert "untrusted.invalid" not in str(submitted)
    # A deleted library ID is rejected even when the caller supplies a usable URL.
    await library.delete_resources(0, [source["id"]])
    with pytest.raises(HTTPException, match="已删除"):
        await video_controller.generate(req, media_base_url="https://app.invalid")


@pytest.mark.asyncio
async def test_folder_deletion_waits_for_upload_and_cancel_is_idempotent(client):
    target = await folder()
    pending = await library.reserve(0, None, "pending.mp4", target.id)
    with pytest.raises(HTTPException, match="正在上传"):
        await library.delete_folder(0, target.id)
    await target.refresh_from_db()
    assert target.deleting is False
    assert (await client.post(f"/api/resource-library/resources/{pending.id}/cancel-upload")).json()["code"] == 0
    assert (await client.post(f"/api/resource-library/resources/{pending.id}/cancel-upload")).json()["code"] == 0
    assert not await VideoResource.filter(id=pending.id).exists()
    await library.delete_folder(0, target.id)
    assert not await ResourceFolder.filter(id=target.id).exists()


@pytest.mark.asyncio
async def test_imports_persisted_scene_and_generated_video_only_for_own_team(client, clip, monkeypatch):
    from models.novel import Novel
    from models.chapter import Chapter
    from models.scene import Scene
    from models.video import Video
    from utils.enums import TaskStatusEnum, VideoModelTypeEnum
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    ctx = AuthContext(user=SimpleNamespace(id=5), membership=SimpleNamespace(role="creator"), team_id=2)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    novel = await Novel.create(name="Owned library source", team_id=2)
    chapter = await Chapter.create(novel=novel, number=1, name="one", content="test")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", metadata={"video_reference_media": [{"type": "video", "url": "/media/clip.mp4"}]})
    video = await Video.create(scene=scene, model_type=VideoModelTypeEnum.seedance.value, status=TaskStatusEnum.completed.value, url="/media/clip.mp4")
    try:
        for payload in (
            {"source": "video", "source_id": video.id, "name": "生成结果"},
            {"source": "scene", "source_id": scene.id, "media_url": "/media/clip.mp4", "name": "参考视频"},
        ):
            response = await client.post("/api/resource-library/import", json=payload)
            assert response.json()["code"] == 0, response.text
            assert response.json()["data"]["storage_ref"] != "/media/clip.mp4"
        ctx.team_id = 3
        response = await client.post("/api/resource-library/import", json={"source": "video", "source_id": video.id, "name": "越权"})
        assert response.json()["code"] == 404
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


@pytest.mark.parametrize('filename,display', [('12.mp4', '12'), ('动作参考.MOV', '动作参考'), ('scene.v2.mp4', 'scene.v2'), ('自定义名称', '自定义名称')])
def test_video_names_hide_only_video_extensions(filename, display):
    from schemas.resource_library import ResourceRename
    from utils.media_name import video_display_name
    assert video_display_name(filename) == display
    assert ResourceRename(name=filename).name == display


@pytest.mark.asyncio
async def test_upload_and_legacy_resource_names_hide_extension_without_changing_storage(client, clip):
    from controllers.resource_library import resource_dict
    from services.resource_references import reference_dict
    uploaded = await client.post('/api/resource-library/upload', files={'file': ('12.mp4', clip.read_bytes(), 'video/mp4')})
    assert uploaded.json()['code'] == 0, uploaded.text
    item = uploaded.json()['data']
    assert item['name'] == '12'
    assert item['filename'] == '12.mp4'
    stored = await resource_for(0, item['id'])
    assert stored.name == '12'
    original_ref = stored.storage_ref
    stored.name = '历史视频.MOV'
    await stored.save()
    assert resource_dict(stored)['name'] == '历史视频'
    assert reference_dict(stored)['name'] == '历史视频'
    response = await client.patch(f'/api/resource-library/resources/{stored.id}', json={'name': '新名称.mp4'})
    assert response.json()['data']['name'] == '新名称'
    await stored.refresh_from_db()
    assert stored.name == '新名称'
    assert stored.storage_ref == original_ref
    assert stored.filename == '12.mp4'
