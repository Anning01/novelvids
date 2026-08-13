import json

import httpx
import pytest
from fastapi import HTTPException

from models.config import AiModelConfig
from services.video.capabilities import validate_selection
from services.video.seedance import SeedanceGenerationError, SeedanceGenerator
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


def test_video_capabilities_are_model_specific():
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
        generation_mode="reference",
    )

    assert task_id == "video-task-1"


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
    assert result["metadata"] == {"duration": 6, "frames": 144}


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
