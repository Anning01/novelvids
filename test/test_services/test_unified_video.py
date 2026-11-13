import json
import traceback
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from models.config import AiModelConfig
from services.video import get_generator
from services.video.capabilities import capabilities_for, validate_protocol, validate_selection
from services.video.base import VideoProviderError
from utils.enums import TaskStatusEnum


async def config_for(model_type="seedance_2_5", base_url="https://video.example.test"):
    return await AiModelConfig.create(task_type=4, name="视频服务", base_url=base_url,
        api_key="private-key", model="configured-model", api_protocol="unified_video",
        video_model_type=model_type, is_active=True)


def test_protocol_capabilities_preserve_ark_and_restrict_unconfirmed_options():
    ark = capabilities_for("seedance_2_5")
    unified = capabilities_for("seedance_2_5", "unified_video")
    assert ark.supports_auto_duration and "mov" in ark.output_formats
    assert not unified.supports_auto_duration
    assert unified.output_formats == ("mp4",)
    assert unified.supports_return_last_frame
    assert not unified.supports_audio_data_uri
    assert capabilities_for("seedance_2", "unified_video").resolutions == ("480p", "720p", "1080p")
    with pytest.raises(HTTPException):
        validate_protocol("seedance_2", "unified_video")
    with pytest.raises(HTTPException):
        validate_protocol("wan_3", "unified_video")
    for override in ({"duration": -1}, {"output_format": "mov"}, {"resolution": "4k"}):
        with pytest.raises(HTTPException):
            validate_selection("seedance_2_5", api_protocol="unified_video", **{
                "generation_mode": "reference", "resolution": "720p", "aspect_ratio": "16:9",
                "duration": 6, "output_format": "mp4", "generate_audio": None, **override})


@pytest.mark.parametrize(("state", "expected"), [("queued", TaskStatusEnum.queued), ("in_progress", TaskStatusEnum.running), ("completed", TaskStatusEnum.completed), ("failed", TaskStatusEnum.failed)])
async def test_query_maps_progress_and_metadata_url_without_exposing_provider(monkeypatch, state, expected):
    config = await config_for()
    client_type = httpx.AsyncClient

    def handler(request):
        assert request.url.path == "/v1/videos/task-1"
        return httpx.Response(200, json={"id": "task-1", "status": state, "progress": 65,
            "metadata": {"url": "https://cdn.example.test/result.mp4", "provider": "private-vendor"},
            "error": {"message": "private-vendor https://private.example.test private-key", "code": "internal"} if state == "failed" else None})

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    result = await get_generator(config).query("task-1")
    assert result["status"] == expected
    assert "private" not in json.dumps(result)
    if state == "completed":
        assert result["url"] == "https://cdn.example.test/result.mp4"
        assert result["progress"] == 100
        assert "last_frame_url" not in result["metadata"]
    elif state == "in_progress":
        assert result["progress"] == 65


async def test_query_preserves_output_moderation_code_without_exposing_provider_details(monkeypatch):
    config = await config_for()
    client_type = httpx.AsyncClient

    def handler(request):
        return httpx.Response(200, json={"id": "task-1", "status": "failed", "error": {
            "code": "OutputVideoSensitiveContentDetected",
            "message": "private-vendor private-key https://private.example.test?token=secret",
        }})

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    result = await get_generator(config).query("task-1")
    assert result["status"] == TaskStatusEnum.failed
    assert "OutputVideoSensitiveContentDetected" in result["metadata"]["error"]
    assert "private" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("phase", ["failed_task"])
@pytest.mark.parametrize("kind", ["privacy", "wrapped_privacy", "image_download", "video_download", "output"])
async def test_public_error_extraction_is_shared_by_submission_and_polling(monkeypatch, phase, kind):
    config = await config_for()
    client_type = httpx.AsyncClient
    if kind in {"privacy", "wrapped_privacy"}:
        code = "InputImageSensitiveContentDetected.PrivacyInformation"
        message = "input image 'content[2]' may contain real person"
    elif kind == "output":
        code = "OutputVideoSensitiveContentDetected"
        message = "The output video may contain sensitive information"
    else:
        code = "InvalidParameterValue"
        param = "content[1].video_url" if kind == "video_download" else "content[1].image_uri"
        message = f"The parameter {param} is not valid: resource download failed"
    error = {"code": code, "message": message + " private-vendor private-key https://private.example.test?token=secret Request id: upstream-123"}
    if kind == "wrapped_privacy":
        error = {"code": "video_generation_failed", "message": "上游 HTTP 400: " + json.dumps({"error": error})}

    def handler(request):
        return httpx.Response(400 if phase == "http_rejection" else 200,
            json={"id": "task-1", "status": "failed", "error": error}, headers={"x-request-id": "gateway-456"})

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    generator = get_generator(config)
    if phase == "failed_task":
        result = await generator.query("task-1")
        assert result["status"] == TaskStatusEnum.failed
        detail = result["metadata"]["error"]
    else:
        with pytest.raises(VideoProviderError) as exc:
            await generator.submit(prompt="A forest", duration=6)
        assert not exc.value.submission_uncertain
        detail = str(exc.value)
    assert code in detail
    assert "upstream-123" in detail
    assert "private" not in detail and "secret" not in detail
    if kind in {"privacy", "wrapped_privacy"}:
        assert "content[2]" in detail and "may contain real person" in detail
    elif kind.endswith("download"):
        assert param in detail and "resource download failed" in detail
    if phase == "http_rejection" or kind == "wrapped_privacy":
        assert "HTTP 400" in detail


@pytest.mark.parametrize("identifier", ["private-key", "sk-" + "s" * 24, "https://private.example.test?token=secret"])
def test_public_error_extraction_never_uses_credentials_as_a_request_id(identifier):
    from services.video.provider_http import public_provider_error

    message = public_provider_error({"error": {
        "code": "InputImageSensitiveContentDetected.PrivacyInformation",
        "message": "input image may contain real person Request id: " + identifier,
        "param": "content[2]", "request_id": identifier,
    }}, transport_request_id=identifier, secrets=("private-key",))
    assert "content[2]" in message
    assert "PrivacyInformation" in message
    assert identifier not in message
    assert "Request id" not in message


async def test_unified_uploads_local_images_through_existing_object_storage(monkeypatch):
    from services.video.public_media import PublicMediaResolver

    storage = type("Storage", (), {"enabled": True, "put_bytes": AsyncMock(), "public_url": lambda self, key: "https://cdn.example.test/" + key})()
    monkeypatch.setattr("services.video.public_media.oss", storage)
    resolver = PublicMediaResolver(team_id=9)
    source = "data:image/png;base64,aW1hZ2U="
    url = await resolver.resolve(source)
    assert url.startswith("https://cdn.example.test/uploads/9/")
    assert await resolver.resolve(source) == url
    storage.put_bytes.assert_awaited_once()
    assert storage.put_bytes.call_args.args[1:] == (b"image", "image/png")


async def test_unified_rejects_base64_without_object_storage(monkeypatch):
    from services.video.public_media import PublicMediaResolver

    monkeypatch.setattr("services.video.public_media.oss", type("Storage", (), {"enabled": False})())
    with pytest.raises(VideoProviderError, match="公网"):
        await PublicMediaResolver(team_id=None).resolve("data:image/png;base64,aW1hZ2U=")


@pytest.mark.parametrize("body", [
    {"id": "task", "status": "completed", "metadata": {}},
    {"id": "task", "status": "unknown"},
    {"id": "task", "status": "completed", "metadata": {"url": "file:///private/video.mp4"}},
])
async def test_invalid_query_results_are_not_marked_as_completed(monkeypatch, body):
    config = await config_for()
    client_type = httpx.AsyncClient
    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), **kw))
    with pytest.raises(VideoProviderError):
        await get_generator(config).query("task")


async def test_local_file_upload_is_scoped_and_rejects_traversal(monkeypatch, tmp_path):
    from services.video.public_media import PublicMediaResolver

    monkeypatch.setattr("services.video.public_media.settings.MEDIA_PATH", str(tmp_path))
    (tmp_path / "image.png").write_bytes(b"image")
    storage = type("Storage", (), {"enabled": True, "put_file": AsyncMock(), "public_url": lambda self, key: "https://cdn.example.test/" + key})()
    monkeypatch.setattr("services.video.public_media.oss", storage)
    assert (await PublicMediaResolver(team_id=7).resolve("/media/image.png")).startswith("https://cdn.example.test/uploads/7/")
    storage.put_file.assert_awaited_once()
    with pytest.raises(VideoProviderError):
        await PublicMediaResolver(team_id=7).resolve("/media/../outside.png")


@pytest.mark.parametrize("source", ["data:image/png,invalid", "data:text/plain;base64,aGVsbG8=", "data:image/png;base64,!!!", "data:image/png;base64,", "https://user:password@example.test/image.png"])
async def test_invalid_media_does_not_reach_storage(monkeypatch, source):
    from services.video.public_media import PublicMediaResolver

    storage = type("Storage", (), {"enabled": True, "put_bytes": AsyncMock()})()
    monkeypatch.setattr("services.video.public_media.oss", storage)
    with pytest.raises(VideoProviderError):
        await PublicMediaResolver(team_id=None).resolve(source)
    storage.put_bytes.assert_not_awaited()


async def test_storage_failure_is_safe_to_retry_and_does_not_leak_details(monkeypatch):
    from services.video.public_media import PublicMediaResolver

    storage = type("Storage", (), {"enabled": True, "put_bytes": AsyncMock(side_effect=RuntimeError("private-vendor private-key"))})()
    monkeypatch.setattr("services.video.public_media.oss", storage)
    with pytest.raises(VideoProviderError) as exc:
        await PublicMediaResolver(team_id=None).resolve("data:image/png;base64,aW1hZ2U=")
    assert not exc.value.submission_uncertain
    assert "private-key" not in "".join(traceback.format_exception(exc.value))
    assert "private" not in str(exc.value)
