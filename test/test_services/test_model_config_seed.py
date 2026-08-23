import pytest

from models.config import AiModelConfig
from services.model_config_seed import DEFAULT_MODELS, ensure_model_config_seed_data
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_ensure_seed_creates_default_models_when_empty():
    created = await ensure_model_config_seed_data()
    assert created == len(DEFAULT_MODELS)

    configs = await AiModelConfig.all()
    assert len(configs) == len(DEFAULT_MODELS)
    assert all(not config.is_active for config in configs)
    assert all(config.api_key == "" for config in configs)

    names = {config.name for config in configs}
    assert "doubao-seedance-2.5" in names
    assert "deepseek" in names


@pytest.mark.asyncio
async def test_ensure_seed_is_idempotent():
    await ensure_model_config_seed_data()
    created = await ensure_model_config_seed_data()
    assert created == 0
    assert await AiModelConfig.all().count() == len(DEFAULT_MODELS)


@pytest.mark.asyncio
async def test_ensure_seed_adds_only_missing_models():
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="deepseek",
        base_url="https://x",
        api_key="k",
        model="m",
    )
    created = await ensure_model_config_seed_data()
    assert created == len(DEFAULT_MODELS) - 1
    assert await AiModelConfig.filter(name="deepseek").count() == 1


@pytest.mark.asyncio
async def test_ensure_seed_upgrades_only_legacy_minimax_zero_price_placeholder():
    legacy = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="legacy-minimax-h3",
        base_url="https://api.minimaxi.com",
        api_key="",
        model="MiniMax-H3",
        api_protocol="minimax",
        video_model_type="minimax_h3",
        pricing={
            "type": "video",
            "currency": "CNY",
            "prices": {"768P": 0.0, "2K": 0.0},
            "video_reference_prices": {"768P": 0.0, "2K": 0.0},
        },
    )

    await ensure_model_config_seed_data()
    await legacy.refresh_from_db()

    assert legacy.pricing["billing_unit"] == "second"
    assert legacy.pricing["prices"] == {"768P": 0.5, "2K": 0.8}
    assert legacy.pricing["input_image"] == {"first_free": 5, "price_per_image": 0.2}
