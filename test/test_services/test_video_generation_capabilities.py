import json

import httpx
import pytest
from fastapi import HTTPException

from models.config import AiModelConfig
from services.video import get_generator, get_record_model_type
from services.video.capabilities import capabilities_for, validate_selection
from services.video.content import prepare_video_content
from services.video.minimax import MiniMaxGenerationError, MiniMaxH3Generator
from services.video.seedance import SeedanceGenerationError, SeedanceGenerator
from services.video.wan import Wan3Generator
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, VideoModelTypeEnum


def test_video_capabilities_are_model_specific():
    assert capabilities_for("seedance_2").max_reference_images == 9
    assert capabilities_for("seedance_2").max_reference_videos == 3
    assert capabilities_for("seedance_2").reference_video_total_duration_max == 15
    assert capabilities_for("seedance_2_5").max_reference_images == 30
    assert capabilities_for("seedance_2_5").max_reference_videos == 10
    assert capabilities_for("seedance_2_5").reference_video_total_duration_max == 30
    standard = validate_selection(
        "seedance_2",
        generation_mode="reference",
        resolution="4k",
        aspect_ratio="21:9",
        duration=15,
        output_format="mp4",
        generate_audio=True,
    )
    assert standard.resolution == "4k"
    assert standard.duration == 15

    with pytest.raises(HTTPException, match="分辨率"):
        validate_selection(
            "seedance_2_fast",
            generation_mode="reference",
            resolution="1080p",
            aspect_ratio="16:9",
            duration=6,
            output_format="mp4",
            generate_audio=True,
        )

    with pytest.raises(HTTPException, match="比例"):
        validate_selection(
            "seedance_2_5",
            generation_mode="keyframes",
            resolution="720p",
            aspect_ratio="16:9",
            duration=30,
            output_format="mov",
            generate_audio=False,
        )

    selection = validate_selection(
        "seedance_2_5",
        generation_mode="keyframes",
        resolution="720p",
        aspect_ratio="adaptive",
        duration=-1,
        output_format="mov",
        generate_audio=False,
    )
    assert selection.duration == -1
    assert selection.output_format == "mov"

    minimax = validate_selection(
        "minimax_h3",
        generation_mode="reference",
        resolution="768p",
        aspect_ratio="16:9",
        duration=15,
        output_format="MP4",
        generate_audio=True,
    )
    assert minimax.resolution == "768P"
    assert minimax.output_format == "mp4"
    assert capabilities_for("minimax_h3").supports_return_last_frame is True

    wan_capabilities = capabilities_for("wan_3")
    assert wan_capabilities.max_reference_images == 10
    assert wan_capabilities.max_reference_videos == 5
    assert wan_capabilities.max_reference_audios == 5
    assert wan_capabilities.input_output_video_duration_max == 30
    assert wan_capabilities.supports_audio_data_uri is False
    assert wan_capabilities.supports_temporary_file_upload is True
    assert wan_capabilities.supports_return_last_frame is True
    wan = validate_selection(
        "wan_3",
        generation_mode="reference",
        resolution="1080p",
        aspect_ratio="adaptive",
        duration=-1,
        output_format="mp4",
        generate_audio=True,
    )
    assert wan.resolution == "1080P"
    assert wan.duration == -1


async def _video_config(model_type: str) -> AiModelConfig:
    return await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name=f"{model_type}-request-test",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="secret",
        model=f"configured-{model_type}-endpoint",
        api_protocol="volcengine_ark",
        video_model_type=model_type,
        is_active=True,
    )


async def _minimax_config(base_url: str = "https://api.minimaxi.com") -> AiModelConfig:
    return await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="minimax-h3-request-test",
        base_url=base_url,
        api_key="minimax-secret",
        model="MiniMax-H3",
        api_protocol="minimax",
        video_model_type="minimax_h3",
        is_active=True,
    )


async def _wan_config(
    base_url: str = "https://workspace.cn-beijing.maas.aliyuncs.com",
) -> AiModelConfig:
    return await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="wan3-request-test",
        base_url=base_url,
        api_key="dashscope-secret",
        model="wan3.0-video",
        api_protocol="dashscope",
        video_model_type="wan_3",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_video_factory_selects_adapter_from_configured_model_type():
    seedance = await _video_config("seedance_2")
    minimax = await _minimax_config()
    wan = await _wan_config()

    seedance_generator = get_generator(seedance)
    minimax_generator = get_generator(minimax)
    assert isinstance(seedance_generator, SeedanceGenerator)
    assert get_record_model_type(seedance) == VideoModelTypeEnum.seedance
    assert isinstance(minimax_generator, MiniMaxH3Generator)
    assert get_record_model_type(minimax) == VideoModelTypeEnum.minimax
    assert isinstance(get_generator(wan), Wan3Generator)
    assert get_record_model_type(wan) == VideoModelTypeEnum.wan


@pytest.mark.asyncio
async def test_wan3_reference_request_and_query_use_dashscope_contract(monkeypatch):
    config = await _wan_config(
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert str(request.url) == (
                "https://workspace.cn-beijing.maas.aliyuncs.com"
                "/api/v1/services/aigc/video-generation/video-synthesis"
            )
            assert request.headers["authorization"] == "Bearer dashscope-secret"
            assert request.headers["x-dashscope-async"] == "enable"
            assert json.loads(request.content) == {
                "model": "wan3.0-video",
                "input": {
                    "prompt": "图1 说话，图2规定构图，视频1规定动作，音频1保持人物声音一致。",
                    "media": [
                        {
                            "type": "reference_image",
                            "url": "https://cdn.example.com/person.png",
                        },
                        {
                            "type": "reference_image",
                            "url": "https://cdn.example.com/composition.png",
                        },
                        {
                            "type": "reference_video",
                            "url": "https://cdn.example.com/motion.mp4",
                        },
                        {
                            "type": "reference_audio",
                            "url": "https://cdn.example.com/voice.mp3",
                        },
                    ],
                },
                "parameters": {
                    "resolution": "720P",
                    "ratio": "9:16",
                    "duration": 8,
                    "audio": True,
                    "prompt_extend": True,
                    "watermark": False,
                },
            }
            return httpx.Response(200, json={
                "output": {"task_status": "PENDING", "task_id": "wan-task-1"},
                "request_id": "submit-request",
            })
        assert str(request.url) == (
            "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/tasks/wan-task-1"
        )
        return httpx.Response(200, json={
            "output": {
                "task_id": "wan-task-1",
                "task_status": "SUCCEEDED",
                "video_url": "https://cdn.example.com/wan-result.mp4",
            },
            "usage": {
                "duration": 8.0,
                "input_video_duration": 3.0,
                "output_video_duration": 8.0,
                "fps": 30,
                "SR": 720,
                "ratio": "9:16",
            },
        })

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.wan.httpx.AsyncClient", client_factory)
    generator = get_generator(config)
    task_id = await generator.submit(
        prompt=(
            "@人物 说话，【参考图片：构图.png】规定构图，"
            "【参考视频：动作.mp4】规定动作，@音频1保持人物声音一致。"
        ),
        subjects=[{
            "name": "人物",
            "images": ["https://cdn.example.com/person.png"],
            "description": "年轻人",
        }],
        duration=8,
        aspect_ratio="9:16",
        resolution="720P",
        generation_mode="reference",
        reference_images=["https://cdn.example.com/composition.png"],
        reference_videos=["https://cdn.example.com/motion.mp4"],
        reference_audios=["https://cdn.example.com/voice.mp3"],
        generate_audio=True,
    )
    result = await generator.query(task_id)

    assert len(requests) == 2
    assert result["status"] == TaskStatusEnum.completed
    assert result["url"] == "https://cdn.example.com/wan-result.mp4"
    assert result["metadata"]["usage"]["fps"] == 30


def test_shared_content_preserves_at_audio_reference_while_resolving_character_images():
    prepared = prepare_video_content(
        prompt="@音频1 对应角色 @{羽宁}，仅参考音色。",
        subjects=[{
            "name": "羽宁",
            "images": ["https://cdn.example.com/yuning.png"],
            "description": "女主角",
        }],
        generation_mode="reference",
        max_reference_images=9,
        reference_audios=["https://cdn.example.com/yuning.wav"],
    )

    assert prepared.prompt == "@音频1 对应角色 [图1]，仅参考音色。"
    assert prepared.items[-1]["role"] == "reference_audio"


@pytest.mark.asyncio
async def test_wan3_keyframes_map_to_first_and_last_frame(monkeypatch):
    config = await _wan_config()

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["input"]["media"] == [
            {"type": "first_frame", "url": "https://cdn.example.com/first.png"},
            {"type": "last_frame", "url": "https://cdn.example.com/last.png"},
        ]
        return httpx.Response(200, json={
            "output": {"task_status": "PENDING", "task_id": "wan-keyframes"},
        })

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.wan.httpx.AsyncClient", client_factory)
    task_id = await get_generator(config).submit(
        prompt="从首帧过渡到尾帧",
        generation_mode="keyframes",
        first_frame_url="https://cdn.example.com/first.png",
        last_frame_url="https://cdn.example.com/last.png",
    )
    assert task_id == "wan-keyframes"


@pytest.mark.asyncio
async def test_wan3_uploads_local_media_to_dashscope_temporary_storage(monkeypatch):
    config = await _wan_config()
    local_image = "data:image/png;base64,aW1hZ2U="
    local_audio = "data:audio/mp3;base64,YXVkaW8="

    async def resolve_media(media, *, api_key, model):
        assert api_key == "dashscope-secret"
        assert model == "wan3.0-video"
        assert [item["url"] for item in media] == [
            local_image,
            "/media/video-references/motion.mp4",
            local_audio,
        ]
        return [
            {**item, "url": f"oss://dashscope-instant/job/{index}"}
            for index, item in enumerate(media, start=1)
        ]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-dashscope-ossresourceresolve"] == "enable"
        payload = json.loads(request.content)
        assert [item["url"] for item in payload["input"]["media"]] == [
            "oss://dashscope-instant/job/1",
            "oss://dashscope-instant/job/2",
            "oss://dashscope-instant/job/3",
        ]
        return httpx.Response(200, json={
            "output": {"task_status": "PENDING", "task_id": "wan-local-media"},
        })

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.wan._resolve_wan_media", resolve_media)
    monkeypatch.setattr("services.video.wan.httpx.AsyncClient", client_factory)

    task_id = await get_generator(config).submit(
        prompt="@人物参考动作并说话",
        subjects=[{"name": "人物", "images": [local_image], "description": "人物"}],
        generation_mode="reference",
        reference_videos=["/media/video-references/motion.mp4"],
        reference_audios=[local_audio],
    )

    assert task_id == "wan-local-media"


@pytest.mark.asyncio
async def test_minimax_h3_request_adapter_uses_v2_contract(monkeypatch):
    config = await _minimax_config("https://api.minimaxi.com/v2/video_generation")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.minimaxi.com/v2/video_generation"
        assert request.headers["authorization"] == "Bearer minimax-secret"
        assert json.loads(request.content) == {
            "model": "MiniMax-H3",
            "content": [
                {"type": "text", "text": "[图1] 穿过晨雾"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://cdn.example.com/person.png"},
                    "role": "reference_image",
                },
                {
                    "type": "video_url",
                    "video_url": {"url": "https://cdn.example.com/motion.mp4"},
                    "role": "reference_video",
                },
                {
                    "type": "audio_url",
                    "audio_url": {"url": "https://cdn.example.com/voice.wav"},
                    "role": "reference_audio",
                },
            ],
            "resolution": "2K",
            "duration": 8,
            "ratio": "9:16",
            "aigc_watermark": False,
        }
        return httpx.Response(200, json={"task_id": "minimax-task-1"})

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.minimax.httpx.AsyncClient", client_factory)
    task_id = await get_generator(config).submit(
        prompt="@人物 穿过晨雾",
        subjects=[{
            "name": "人物",
            "images": ["https://cdn.example.com/person.png"],
            "description": "年轻人",
        }],
        duration=8,
        aspect_ratio="9:16",
        resolution="2k",
        generation_mode="reference",
        reference_videos=["https://cdn.example.com/motion.mp4"],
        reference_audios=["https://cdn.example.com/voice.wav"],
        generate_audio=True,
    )

    assert task_id == "minimax-task-1"


@pytest.mark.asyncio
async def test_minimax_h3_keyframes_force_adaptive_and_query_nested_task(monkeypatch):
    config = await _minimax_config("https://api.minimaxi.com/v2")
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["ratio"] == "adaptive"
            assert payload["content"][1]["role"] == "first_frame"
            assert payload["content"][2]["role"] == "last_frame"
            assert "generate_audio" not in payload
            assert "return_last_frame" not in payload
            return httpx.Response(200, json={"task_id": "h3-keyframes"})
        assert str(request.url) == "https://api.minimaxi.com/v2/query/video_generation/h3-keyframes"
        return httpx.Response(200, json={
            "task": {
                "id": "h3-keyframes",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/h3.mp4"},
                "duration": 6,
                "resolution": "768P",
                "ratio": "adaptive",
                "usage": {"total_tokens": 123},
            },
        })

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.minimax.httpx.AsyncClient", client_factory)
    generator = get_generator(config)
    task_id = await generator.submit(
        prompt="人物从首帧动作过渡到尾帧",
        duration=6,
        aspect_ratio="16:9",
        resolution="768P",
        generation_mode="keyframes",
        first_frame_url="https://cdn.example.com/first.png",
        last_frame_url="https://cdn.example.com/last.png",
    )
    result = await generator.query(task_id)

    assert len(requests) == 2
    assert result["status"] == TaskStatusEnum.completed
    assert result["url"] == "https://cdn.example.com/h3.mp4"
    assert result["metadata"]["usage"] == {"total_tokens": 123}


@pytest.mark.asyncio
async def test_minimax_h3_structured_error_is_sanitized(monkeypatch):
    config = await _minimax_config()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            headers={"x-request-id": "minimax-request-400"},
            json={"error": {"code": "invalid_params", "message": "duration 参数超出范围"}},
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.minimax.httpx.AsyncClient", client_factory)
    with pytest.raises(MiniMaxGenerationError) as exc_info:
        await get_generator(config).submit(prompt="private prompt")

    message = str(exc_info.value)
    assert "duration 参数超出范围" in message
    assert "invalid_params" in message
    assert "minimax-request-400" in message
    assert "private prompt" not in message


@pytest.mark.asyncio
async def test_seedance_2_5_outbound_request_uses_documented_task_protocol(monkeypatch):
    config = await _video_config("seedance_2_5")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload == {
            "model": "configured-seedance_2_5-endpoint",
            "content": [
                {"type": "text", "text": "[图1] 在雨中奔跑"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://cdn.example.com/person.png"},
                    "role": "reference_image",
                },
            ],
            "duration": 12,
            "resolution": "720p",
            "ratio": "9:16",
            "generate_audio": True,
            "return_last_frame": True,
            "watermark": False,
            "output_format": "mov",
        }
        return httpx.Response(200, json={"id": "video-task-1"})

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.seedance.httpx.AsyncClient", client_factory)
    task_id = await SeedanceGenerator(config).submit(
        prompt="@人物 在雨中奔跑",
        subjects=[{
            "name": "人物",
            "images": ["https://cdn.example.com/person.png"],
            "description": "年轻人",
        }],
        duration=12,
        aspect_ratio="9:16",
        resolution="720p",
        output_format="mov",
        generate_audio=True,
        return_last_frame=True,
        generation_mode="reference",
    )

    assert task_id == "video-task-1"


@pytest.mark.asyncio
async def test_seedance_reference_uploads_are_appended_with_official_roles(monkeypatch):
    config = await _video_config("seedance_2_5")

    async def handler(request: httpx.Request) -> httpx.Response:
        content = json.loads(request.content)["content"]
        assert content == [
            {
                "type": "text",
                "text": "@音频1 对应角色 [图1]，仅用于参考人物音色。镜头推进",
            },
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,asset"},
                "role": "reference_image",
            },
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,upload"},
                "role": "reference_image",
            },
            {
                "type": "video_url",
                "video_url": {"url": "https://media.example.com/reference.mp4"},
                "role": "reference_video",
            },
            {
                "type": "audio_url",
                "audio_url": {"url": "https://media.example.com/voice.wav"},
                "role": "reference_audio",
            },
        ]
        return httpx.Response(200, json={"id": "reference-task"})

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.seedance.httpx.AsyncClient", client_factory)
    task_id = await SeedanceGenerator(config).submit(
        prompt="@音频1 对应角色 @{人物}，仅用于参考人物音色。镜头推进",
        subjects=[{"name": "人物", "images": ["data:image/png;base64,asset"]}],
        reference_images=["data:image/png;base64,upload"],
        reference_videos=["https://media.example.com/reference.mp4"],
        reference_audios=["https://media.example.com/voice.wav"],
        generation_mode="reference",
    )

    assert task_id == "reference-task"


@pytest.mark.asyncio
async def test_seedance_keyframes_and_query_nested_video_url(monkeypatch):
    config = await _video_config("seedance_2")
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["content"][1]["role"] == "first_frame"
            assert payload["content"][2]["role"] == "last_frame"
            assert "output_format" not in payload
            return httpx.Response(200, json={"id": "keyframe-task"})
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "content": {"video_url": {"url": "https://cdn.example.com/result.mp4"}},
                "last_frame_url": "https://cdn.example.com/result-last.png",
                "duration": 6,
                "frames": 144,
            },
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.seedance.httpx.AsyncClient", client_factory)
    generator = SeedanceGenerator(config)
    task_id = await generator.submit(
        prompt="镜头缓慢推进",
        duration=6,
        aspect_ratio="adaptive",
        resolution="1080p",
        generation_mode="keyframes",
        first_frame_url="https://cdn.example.com/first.png",
        last_frame_url="https://cdn.example.com/last.png",
    )
    result = await generator.query(task_id)

    assert len(requests) == 2
    assert result["status"] == TaskStatusEnum.completed
    assert result["url"] == "https://cdn.example.com/result.mp4"
    assert result["metadata"] == {
        "duration": 6,
        "frames": 144,
        "last_frame_url": "https://cdn.example.com/result-last.png",
    }


@pytest.mark.asyncio
async def test_seedance_http_error_is_sanitized(monkeypatch):
    config = await _video_config("seedance_2_fast")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            headers={"x-request-id": "video-request-422"},
            text="upstream body containing private prompt and token",
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.seedance.httpx.AsyncClient", client_factory)
    with pytest.raises(SeedanceGenerationError, match="HTTP 422.*video-request-422") as exc_info:
        await SeedanceGenerator(config).submit(prompt="private prompt")

    assert "private prompt" not in str(exc_info.value)
    assert "token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_seedance_http_error_surfaces_structured_provider_detail(monkeypatch):
    config = await _video_config("seedance_2_fast")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            headers={"x-request-id": "video-request-400"},
            json={
                "error": {
                    "code": "InvalidParameter",
                    "message": "参考图片数量超出当前模型限制",
                },
            },
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.seedance.httpx.AsyncClient", client_factory)
    with pytest.raises(SeedanceGenerationError) as exc_info:
        await SeedanceGenerator(config).submit(prompt="镜头缓慢推进")

    message = str(exc_info.value)
    assert "参考图片数量超出当前模型限制" in message
    assert "InvalidParameter" in message
    assert "HTTP 400" in message
    assert "video-request-400" in message
