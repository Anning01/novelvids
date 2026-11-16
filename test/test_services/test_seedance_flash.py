import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from config import settings
from models.config import AiModelConfig
from prompts.skill_pack import read_skill
from prompts.skills.scripts.select_video_optimizer import select
from prompts.storyboard_sheet_binding import model_image_format
from services import studio_platform
from services.platform.videos import VideoRequest, video_options
from services.video.capabilities import capabilities_for, validate_selection
from services.video.factory import video_generator_factory
from services.video.unified import UnifiedVideoGenerator

MODEL = "seedance_2_5_flash"


def test_flash_capabilities_preserve_25_and_platform_contract():
    caps = capabilities_for(MODEL)
    assert caps.resolutions == ("480p", "720p")
    assert (caps.max_reference_images, caps.max_reference_videos, caps.max_reference_audios) == (10, 5, 5)
    assert (caps.duration_min, caps.duration_max) == (4, 30)
    assert caps.reference_video_total_duration_max == caps.reference_audio_total_duration_max == 30
    assert caps.supports_auto_duration and caps.output_formats == ("mp4", "mov")
    assert capabilities_for("seedance_2_5").max_reference_images == 30
    assert "1080p" in capabilities_for("seedance_2_5").resolutions
    platform = capabilities_for(MODEL, "novelvids")
    assert platform.output_formats == ("mp4",) and not platform.supports_auto_duration
    options = dict(generation_mode="reference", resolution="720p", aspect_ratio="16:9",
                   duration=30, output_format="mp4", generate_audio=True)
    assert validate_selection(MODEL, api_protocol="novelvids", **options).duration == 30
    assert validate_selection(MODEL, **{**options, "generation_mode": "keyframes", "aspect_ratio": "adaptive"})
    for override in ({"resolution": "1080p"}, {"duration": 31}, {"duration": -1}, {"output_format": "mov"}):
        with pytest.raises(HTTPException):
            validate_selection(MODEL, api_protocol="novelvids", **{**options, **override})


@pytest.mark.parametrize("kind,limit", [("image", 10), ("video", 5), ("audio", 5)])
def test_flash_reference_limits(kind, limit):
    config = SimpleNamespace(task_types=[4], api_protocol="volcengine_ark", video_model_type=MODEL,
                             pricing={"type": "video", "prices": {"720p": 1}})
    def request(count):
        return VideoRequest(model="nv-1", prompt="Pan", duration=30,
            references=[{"type": kind, "url": f"https://media.example/{i}"} for i in range(count)]).model_dump(mode="json")
    assert video_options(config, request(limit)) == config.pricing
    with pytest.raises(HTTPException, match="参考素材数量"):
        video_options(config, request(limit + 1))


async def test_flash_sync_submit_and_poll_reuse_platform_protocol(monkeypatch):
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_BASE_URL", "https://platform.example")
    client_type = httpx.AsyncClient
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "nv-231", "name": "Flash",
                "task_types": [4], "video_model_type": MODEL,
                "pricing": {"type": "video", "prices": {"480p": 1, "720p": 2}}}]})
        if request.method == "POST":
            assert request.url.path == "/v1/videos"
            body = json.loads(request.content)
            assert body["model"] == "nv-231"
            assert body["duration"] == 30 and body["resolution"] == "720p"
            assert body["prompt"] == "参考 @image1"
            return httpx.Response(200, json={"id": "flash-task", "status": "queued"})
        assert request.url.path == "/v1/videos/flash-task"
        return httpx.Response(200, json={"id": "flash-task", "status": "completed", "progress": 100,
            "metadata": {"url": "https://media.example/result.mp4"}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_type(**{**kw, "transport": httpx.MockTransport(respond)}))
    for _ in range(2):
        assert await studio_platform.sync_platform_models("fixture-key") == {"connected": True, "synced": 1}
    config = await AiModelConfig.get(scope=studio_platform.SYNC_SCOPE, model="nv-231")
    assert config.video_model_type == MODEL and config.api_protocol == "novelvids"
    assert config.pricing["prices"] == {"480p": 1, "720p": 2}
    generator = video_generator_factory.create(config)
    assert isinstance(generator, UnifiedVideoGenerator)
    task_id = await generator.submit("参考 @图片1", duration=30, resolution="720p")
    result = await generator.query(task_id)
    assert result["url"] == "https://media.example/result.mp4"
    assert len(calls) == 4


def test_flash_reuses_25_optimizer_and_image_syntax(tmp_path):
    registry = json.loads(read_skill("video_prompt_models"))
    entry = tmp_path / ".agents/skills/sd25-pe/SKILL.md"
    entry.parent.mkdir(parents=True)
    entry.write_text("Provider instructions")
    for name in (MODEL, "Seedance 2.5 Flash", "seedance-2.5-flash", "doubao-seedance-2-5-flash-261115"):
        result = select(tmp_path, name, registry)
        assert result["model_type"] == MODEL
        assert result["skill"] == "sd25-pe" and result["mode"] == "optimize"
    assert model_image_format(MODEL) == model_image_format("seedance_2_5") == "@图片{}"
