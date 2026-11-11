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
    validate_protocol("seedance_2", "unified_video")
    with pytest.raises(HTTPException):
        validate_protocol("wan_3", "unified_video")
    for override in ({"duration": -1}, {"output_format": "mov"}, {"resolution": "4k"}):
        with pytest.raises(HTTPException):
            validate_selection("seedance_2_5", api_protocol="unified_video", **{
                "generation_mode": "reference", "resolution": "720p", "aspect_ratio": "16:9",
                "duration": 6, "output_format": "mp4", "generate_audio": None, **override})


@pytest.mark.parametrize("base_url", ["https://video.example.test", "https://video.example.test/v1/", "https://video.example.test/v1/videos"])
async def test_submit_translates_references_and_sends_only_confirmed_fields(monkeypatch, base_url):
    config = await config_for(base_url=base_url)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "task-1", "status": "queued", "progress": 0})

    client_type = httpx.AsyncClient
    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    task_id = await get_generator(config).submit(
        prompt="@{角色}和[图2]，【参考视频：动作】，@音频1，[音频1]。",
        subjects=[{"name": "角色", "images": ["https://cdn.example.test/actor.png"]}],
        reference_images=["https://cdn.example.test/scene.png"],
        reference_videos=["https://cdn.example.test/motion.mp4"],
        reference_audios=["https://cdn.example.test/voice.mp3"],
        duration=8, aspect_ratio="16:9", resolution="1080p", output_format="mp4",
        generate_audio=False, return_last_frame=True,
    )
    assert task_id == "task-1"
    assert str(requests[0].url) == "https://video.example.test/v1/videos"
    assert requests[0].headers["authorization"] == "Bearer private-key"
    assert json.loads(requests[0].content) == {
        "model": "configured-model", "prompt": "@image1和@image2，@video1，@audio1，@audio1。",
        "duration": 8, "aspect_ratio": "16:9", "resolution": "1080p", "watermark": False,
        "references": [
            {"type": "image", "role": "reference", "url": "https://cdn.example.test/actor.png"},
            {"type": "image", "role": "reference", "url": "https://cdn.example.test/scene.png"},
            {"type": "video", "role": "reference", "url": "https://cdn.example.test/motion.mp4"},
            {"type": "audio", "role": "reference", "url": "https://cdn.example.test/voice.mp3"},
        ],
    }


async def test_text_to_video_omits_optional_references_instead_of_sending_an_empty_list(monkeypatch):
    config = await config_for("seedance_2_mini")
    client_type = httpx.AsyncClient

    def handler(request):
        payload = json.loads(request.content)
        if payload.get("references") == []:
            return httpx.Response(400, json={"error": {"code": "invalid_references",
                "message": "references must contain at least one item"}})
        assert "references" not in payload
        assert payload["prompt"] == "雨夜街头，镜头缓慢推进。"
        assert payload["duration"] == 5
        assert payload["resolution"] == "480p"
        return httpx.Response(200, json={"id": "text-video-task"})

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    assert await get_generator(config).submit(prompt="雨夜街头，镜头缓慢推进。",
        duration=5, resolution="480p", aspect_ratio="16:9") == "text-video-task"


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


@pytest.mark.parametrize("phase", ["http_rejection", "receipt_rejection", "failed_task"])
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


@pytest.mark.parametrize("model_type", ["seedance_2", "seedance_2_fast", "seedance_2_mini", "seedance_2_5"])
async def test_config_persists_protocol_and_exposes_matching_capabilities(model_type):
    from controllers.config import ai_model_config_controller
    from schemas.config import AiModelConfigCreate
    from services.video.unified import UnifiedVideoGenerator
    from tortoise import Tortoise

    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=4, name="视频服务", base_url="https://video.example.test", api_key="key",
        model="configured-model", api_protocol="unified_video", video_model_type=model_type, is_active=True))
    # Safe startup remains compatible with existing rows on repeated starts.
    await Tortoise.generate_schemas(safe=True)
    await Tortoise.generate_schemas(safe=True)
    saved = await AiModelConfig.get(id=config.id)
    assert saved.api_protocol == "unified_video"
    assert isinstance(get_generator(saved), UnifiedVideoGenerator)
    models = await ai_model_config_controller.list_active_video_models()
    caps = next(item["capabilities"] for item in models if item["config_id"] == config.id)
    assert not caps["supports_auto_duration"]
    assert caps["supports_return_last_frame"]
    assert caps["output_formats"] == ["mp4"]
    assert "4k" not in caps["resolutions"]
    options = (await ai_model_config_controller.list_generation_capabilities())["video_protocols"][model_type]
    assert [item["value"] for item in options] == ["volcengine_ark", "unified_video", "novelvids"]
    assert options[1]["label"] == "通用视频接口"
    assert "https://" not in json.dumps(options)


async def test_keyframes_use_input_roles_without_requesting_output_frame(monkeypatch):
    config = await config_for()
    client_type = httpx.AsyncClient

    def handler(request):
        payload = json.loads(request.content)
        assert payload["references"] == [
            {"type": "image", "role": "first_frame", "url": "https://cdn.example.test/first.png"},
            {"type": "image", "role": "last_frame", "url": "https://cdn.example.test/last.png"},
        ]
        assert "return_last_frame" not in payload
        return httpx.Response(200, json={"id": "keyframes"})

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    assert await get_generator(config).submit(prompt="首尾帧", generation_mode="keyframes", aspect_ratio="adaptive",
        first_frame_url="https://cdn.example.test/first.png", last_frame_url="https://cdn.example.test/last.png",
        return_last_frame=True) == "keyframes"


@pytest.mark.parametrize(("response", "uncertain"), [
    (httpx.Response(400, json={"error": {"message": "private-key private-vendor"}}), False),
    (httpx.Response(503, text="private-vendor private-key"), True),
    (httpx.Response(200, text="not-json private-key"), True),
    (httpx.Response(200, json=[]), True),
    (httpx.Response(200, json={"id": " "}), True),
    (httpx.Response(200, json={"error": {"message": "private-vendor"}}), False),
])
async def test_submit_errors_are_generic_and_preserve_submission_certainty(monkeypatch, response, uncertain):
    config = await config_for()
    client_type = httpx.AsyncClient
    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(lambda request: response), **kw))
    with pytest.raises(VideoProviderError) as exc:
        await get_generator(config).submit(prompt="测试")
    assert exc.value.submission_uncertain is uncertain
    assert "private-key" not in "".join(traceback.format_exception(exc.value))
    assert "private" not in str(exc.value)


@pytest.mark.parametrize(("exception", "uncertain"), [(httpx.ConnectTimeout, False), (httpx.ReadTimeout, True)])
async def test_network_failures_do_not_cause_unsafe_duplicate_submissions(monkeypatch, exception, uncertain):
    config = await config_for()
    client_type = httpx.AsyncClient

    def handler(request):
        raise exception("private-key private-vendor", request=request)

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(VideoProviderError) as exc:
        await get_generator(config).submit(prompt="测试")
    assert exc.value.submission_uncertain is uncertain
    assert "private-key" not in "".join(traceback.format_exception(exc.value))
    assert "private" not in str(exc.value)


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


async def test_repeated_video_mentions_keep_the_correct_reference_order(monkeypatch):
    config = await config_for()
    client_type = httpx.AsyncClient

    def handler(request):
        assert json.loads(request.content)["prompt"] == "先@video2，再@video1，然后@video2。"
        return httpx.Response(200, json={"id": "task"})

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    await get_generator(config).submit(prompt="先【参考视频：乙】，再【参考视频：甲】，然后【参考视频：乙】。",
        reference_videos=["https://cdn.example.test/a.mp4", "https://cdn.example.test/b.mp4"],
        reference_video_names=["甲", "乙"])


async def test_storage_failure_is_safe_to_retry_and_does_not_leak_details(monkeypatch):
    from services.video.public_media import PublicMediaResolver

    storage = type("Storage", (), {"enabled": True, "put_bytes": AsyncMock(side_effect=RuntimeError("private-vendor private-key"))})()
    monkeypatch.setattr("services.video.public_media.oss", storage)
    with pytest.raises(VideoProviderError) as exc:
        await PublicMediaResolver(team_id=None).resolve("data:image/png;base64,aW1hZ2U=")
    assert not exc.value.submission_uncertain
    assert "private-key" not in "".join(traceback.format_exception(exc.value))
    assert "private" not in str(exc.value)


async def test_generation_to_completion_uses_local_tail_extraction_and_stable_video_bindings(monkeypatch):
    from controllers.video import video_controller
    from models.novel import Novel
    from models.chapter import Chapter
    from models.scene import Scene
    from schemas.video import VideoGenerateRequest, VideoReferenceMedia
    from services.video.reference_media import reference_mention_syntax

    novel = await Novel.create(name="视频测试", author="测试")
    chapter = await Chapter.create(novel=novel, number=1, name="测试", content="测试")
    first_url, second_url = "https://cdn.example.test/a.mp4", "https://cdn.example.test/b.mp4"
    first, second = reference_mention_syntax("video", first_url), reference_mention_syntax("video", second_url)
    scene = await Scene.create(chapter=chapter, sequence=1, duration=6,
        prompt=f"先{second}，再{first}，然后{second}。")
    next_scene = await Scene.create(chapter=chapter, sequence=2, prompt="下一镜", duration=6)
    config = await config_for()
    client_type = httpx.AsyncClient

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert "先@video2，再@video1，然后@video2。" in body["prompt"]
            assert "return_last_frame" not in body and "output_format" not in body and "generate_audio" not in body
            return httpx.Response(200, json={"id": "complete-task"})
        return httpx.Response(200, json={"id": "complete-task", "status": "completed", "progress": 100,
            "metadata": {"url": "https://cdn.example.test/result.mp4", "last_frame_url": "https://private.example.test/tail.png"}})

    monkeypatch.setattr("services.video.unified.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    download = AsyncMock(return_value="/media/videos/result.mp4")
    extract = AsyncMock(return_value="/media/videos/tail.png")
    monkeypatch.setattr("controllers.video._download_video", download)
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", extract)
    video = await video_controller._submit_generation(VideoGenerateRequest(scene_id=scene.id, model_config_id=config.id,
        return_last_frame=True, reference_media=[
            VideoReferenceMedia(type="video", url=first_url, name="甲", duration=3),
            VideoReferenceMedia(type="video", url=second_url, name="乙", duration=3),
        ]))
    assert video.external_task_id == "complete-task"
    result = await video_controller.query_status(video.id)
    download.assert_awaited_once_with("https://cdn.example.test/result.mp4", video.id)
    extract.assert_awaited_once_with("/media/videos/result.mp4", video.id, team_id=None)
    assert result.metadata["last_frame_source"] == "ffmpeg"
    assert "private.example.test" not in json.dumps(result.metadata)
    await next_scene.refresh_from_db()
    assert next_scene.metadata["video_reference_media"][0]["url"] == "/media/videos/tail.png"
