from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from config import settings
from controllers.config import ai_model_config_controller
from models.config import AiModelConfig, StudioPlatformConnection
from schemas.config import AiModelConfigOut, VideoGenerationModelOut
from services import studio_platform
from services.video import get_generator, get_record_model_type
from services.video.capabilities import capabilities_for, capabilities_for_config
from services.video.unified import UnifiedVideoGenerator
from utils.enums import VideoModelTypeEnum


@pytest.mark.asyncio
async def test_unknown_video_type_syncs_generates_and_refreshes(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    connection = await StudioPlatformConnection.create(id=1, api_key="studio-test")
    profile = replace(capabilities_for("seedance_2", "novelvids"), resolutions=("720p",),
                      duration_min=5, duration_max=10, duration_choices=(5, 8, 10),
                      max_reference_images=1, max_reference_videos=0, max_reference_audios=0,
                      supports_audio=False, default_generate_audio=False).public_dict()
    entry = studio_platform.CatalogModel(
        id="nv-812", name="New catalog model", task_types=[4], video_model_type="unknown_future_video",
        video_capabilities=profile, pricing={"type":"video","billing_unit":"second","prices":{"720p":1}},
    )
    catalog = studio_platform.Catalog(data=[entry])
    monkeypatch.setattr(studio_platform, "_read_platform_catalog", AsyncMock(return_value=(
        connection, "https://cat.example/v1", "studio-test", catalog)))
    assert (await studio_platform.sync_platform_models())["synced"] == 1
    cfg = await AiModelConfig.get(model="nv-812")
    assert AiModelConfigOut.model_validate(cfg).video_model_type == "unknown_future_video"
    listed = await ai_model_config_controller.list_active_video_models()
    current = VideoGenerationModelOut.model_validate(next(row for row in listed if row["config_id"] == cfg.id))
    assert current.capabilities.duration_choices == [5, 8, 10]
    assert get_record_model_type(cfg) == VideoModelTypeEnum.platform_video
    gen = get_generator(cfg)
    assert isinstance(gen, UnifiedVideoGenerator)
    request = AsyncMock(return_value={"id": "platform-task"})
    monkeypatch.setattr(gen, "_request", request)
    with pytest.raises(HTTPException):
        await gen.submit("pan", duration=6, resolution="720p")
    assert await gen.submit("pan", duration=8, resolution="720p") == "platform-task"
    assert request.await_args.kwargs["payload"]["model"] == "nv-812"

    entry.video_capabilities = {**profile, "duration_choices": [5, 10]}
    with pytest.raises(HTTPException):
        await studio_platform.validate_model_activation(cfg)
    await studio_platform.sync_platform_models()
    await cfg.refresh_from_db()
    assert capabilities_for_config(cfg).duration_choices == (5, 10)
    await studio_platform.validate_model_activation(cfg)

    entry.video_capabilities = {**profile, "duration_max": 0}
    assert "nv-812" in (await studio_platform.sync_platform_models())["unsupported"]
    await cfg.refresh_from_db()
    assert not cfg.is_active
    entry.video_capabilities = None
    assert "nv-812" in (await studio_platform.sync_platform_models())["unsupported"]
