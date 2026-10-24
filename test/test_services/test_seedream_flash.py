"""Seedream Flash capability, request, billing and upgrade contracts."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from controllers.asset import asset_controller
from models.asset import Asset
from models.config import AiModelConfig
from models.novel import Novel
from schemas.config import AiModelConfigCreate
from services.billing.catalog import pricing_for
from services.billing.pricing import compute_image_cost, compute_input_image_cost
from services.image_generation.adapters import ImageGenerationInput, image_protocol_adapter
from services.image_generation.capabilities import (
    COMMON_SEEDREAM_RATIOS,
    capabilities_for,
    validate_protocol,
    validate_selection,
)
from services.model_config_seed import ensure_model_config_seed_data
from utils.enums import AiTaskTypeEnum


MODEL_TYPE = "seedream_5_flash"
MODEL_ID = "doubao-seedream-5-0-flash-260915"


@pytest.mark.parametrize("clarity", ["1K", "1.5K", "2K"])
@pytest.mark.parametrize("ratio", COMMON_SEEDREAM_RATIOS)
def test_flash_dimensions_and_flat_pricing(clarity, ratio):
    selection = validate_selection(
        MODEL_TYPE, clarity=clarity, aspect_ratio=ratio,
        output_format="jpeg", generation_count=1,
    )
    width, height = map(int, selection.provider_size.split("x"))
    assert 921600 <= width * height <= 4624220
    assert 1 / 16 <= width / height <= 16
    pricing = pricing_for(SimpleNamespace(image_model_type=MODEL_TYPE))
    assert compute_image_cost(1, clarity, pricing) == Decimal("0.12")
    assert compute_image_cost(0, clarity, pricing) == 0
    assert compute_input_image_cost(10, pricing) == 0


@pytest.mark.parametrize("override", [
    {"clarity": "4K"}, {"output_format": "webp"},
    {"generation_count": 2}, {"aspect_ratio": "99:1"},
])
def test_flash_rejects_unsupported_parameters(override):
    params = dict(clarity="2K", aspect_ratio="16:9", output_format="png", generation_count=1)
    with pytest.raises(HTTPException):
        validate_selection(MODEL_TYPE, **(params | override))


def test_flash_request_uses_official_ark_shape():
    validate_protocol(MODEL_TYPE, "volcengine_ark")
    with pytest.raises(HTTPException):
        validate_protocol(MODEL_TYPE, "openai_compatible")
    selection = validate_selection(
        MODEL_TYPE, clarity=None, aspect_ratio=None,
        output_format=None, generation_count=None,
    )
    assert capabilities_for(MODEL_TYPE).default_clarity == "2K"
    prepared = image_protocol_adapter("volcengine_ark").prepare(ImageGenerationInput(
        model=MODEL_ID, prompt="cover", resolution=selection.provider_size,
        output_format=selection.output_format, extra_body={"image": ["https://example.com/ref.png"]},
    ))
    assert prepared.path == "/images/generations"
    assert prepared.payload == {
        "model": MODEL_ID, "prompt": "cover", "response_format": "url",
        "watermark": False, "size": "2816x1584", "output_format": "png",
        "image": ["https://example.com/ref.png"],
    }


@pytest.mark.asyncio
async def test_flash_seed_upgrades_existing_installation_and_preserves_custom_prices():
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value, name="existing-image",
        base_url="https://example.com", api_key="", model="existing",
        image_model_type="seedream_5_lite",
    )
    await ensure_model_config_seed_data()
    config = await AiModelConfig.get(image_model_type=MODEL_TYPE)
    assert config.model == MODEL_ID
    assert config.api_key == ""
    assert config.is_active is False
    assert config.pricing["prices"] == {"1K": 0.12, "1.5K": 0.12, "2K": 0.12}
    config.pricing = {"type": "image", "currency": "CNY", "prices": {"2K": 0.09}}
    await config.save()
    assert await ensure_model_config_seed_data() == 0
    await config.refresh_from_db()
    assert config.pricing["prices"] == {"2K": 0.09}


@pytest.mark.asyncio
async def test_flash_can_be_configured_and_listed_via_api(client):
    payload = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="flash", base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="", model=MODEL_ID, api_protocol="volcengine_ark",
        image_model_type=MODEL_TYPE, is_active=True,
    )
    await AiModelConfig.create(**payload.model_dump(mode="json", exclude_none=True))
    response = await client.get("/api/config/image-generation/models")
    assert response.status_code == 200
    model = response.json()["data"][0]
    assert model["model_type"] == MODEL_TYPE
    assert model["capabilities"]["clarities"] == ["1K", "1.5K", "2K"]
    assert model["capabilities"]["default_clarity"] == "2K"


@pytest.mark.asyncio
async def test_flash_asset_request_and_reference_limit(configured_creation_agent):
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value, name="flash",
        base_url="https://ark.cn-beijing.volces.com/api/v3", api_key="",
        model=MODEL_ID, api_protocol="volcengine_ark",
        image_model_type=MODEL_TYPE, is_active=True,
    )
    novel = await Novel.create(name="Flash test", author="Test")
    asset = await Asset.create(
        novel_id=novel.id, asset_type=1, canonical_name="Flash character",
        metadata={"model_config_id": config.id},
    )
    references = [f"https://example.com/{index}.png" for index in range(11)]
    with pytest.raises(HTTPException, match="10"):
        await asset_controller.reference(asset.id, reference_images=references)
    task = await asset_controller.reference(asset.id, reference_images=references[:10])
    assert task.request_params["model"] == MODEL_ID
    assert task.request_params["resolution"] == "2816x1584"
    assert len(task.request_params["reference_images"]) == 10
