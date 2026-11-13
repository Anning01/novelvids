import pytest
from fastapi import HTTPException

from models.config import AiModelConfig
from services.video import get_generator
from services.video.ark_migration import legacy_query_config, migrate_legacy_video_channels
from services.video.base import VideoProviderError
from services.video.capabilities import protocol_options, validate_protocol


@pytest.mark.parametrize("base_url", ["https://example.test/v1", "https://example.test/v1/videos"])
async def test_legacy_channel_moves_to_ark_without_changing_credentials_or_prices(base_url):
    config = await AiModelConfig.create(
        task_type=4, name="Discount channel", model="seedance-test",
        video_model_type="seedance_2_mini", api_protocol="unified_video",
        base_url=base_url, api_key="fixture", pricing={"prices": {"480p": 23}},
    )
    await migrate_legacy_video_channels()
    await migrate_legacy_video_channels()
    await config.refresh_from_db()
    assert config.api_protocol == "volcengine_ark"
    assert config.base_url == "https://example.test/api/v3"
    assert config.api_key == "fixture" and config.pricing == {"prices": {"480p": 23}}
    previous = legacy_query_config(config)
    assert previous.base_url == base_url and previous.model == config.model
    with pytest.raises(VideoProviderError):
        await get_generator(previous).submit(prompt="fixture")
    with pytest.raises(HTTPException):
        validate_protocol(config.video_model_type, "unified_video")
    assert {item["value"] for item in protocol_options()[config.video_model_type]} == {"volcengine_ark", "novelvids"}
