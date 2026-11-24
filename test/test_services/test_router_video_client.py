from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from services.video.capabilities import capabilities_for_config, protocol_options, validate_selection
from services.video.factory import video_generator_factory
from services.video.unified import UnifiedVideoGenerator


@pytest.mark.parametrize("kind,seconds,resolution,ratio", [
    ("muse_video", 5, "720p", "9:16"),
    ("grok_imagine_video_1_5", 1, "480p", "adaptive"),
])
def test_synced_router_video_uses_platform_protocol(kind, seconds, resolution, ratio):
    config = SimpleNamespace(api_protocol="novelvids", video_model_type=kind, scope="studio_platform",
                             pricing={"type": "video", "prices": {resolution: 1}})
    assert isinstance(video_generator_factory.create(config), UnifiedVideoGenerator)
    caps = capabilities_for_config(config)
    assert [item["value"] for item in protocol_options()[kind]] == ["novelvids"]
    selection = dict(generation_mode="reference", output_format="mp4", aspect_ratio=ratio,
                     resolution=resolution, generate_audio=None)
    assert validate_selection(caps, duration=seconds, **selection).duration == seconds
    if kind == "muse_video":
        with pytest.raises(HTTPException):
            validate_selection(caps, duration=7, **selection)
