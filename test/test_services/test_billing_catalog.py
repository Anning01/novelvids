from types import SimpleNamespace

from services.billing.catalog import pricing_for


def test_pricing_for_image_model():
    config = SimpleNamespace(
        image_model_type="seedream_5_pro",
        video_model_type=None,
        model="doubao-seedream-5-0-pro",
    )
    pricing = pricing_for(config)
    assert pricing["type"] == "image"
    assert pricing["prices"]["1K"] == 0.30
    assert pricing["prices"]["2K"] == 0.60
    assert pricing["input_image"] == {"first_free": 1, "price_per_image": 0.02}


def test_pricing_for_image_model_flat():
    config = SimpleNamespace(
        image_model_type="seedream_5_lite",
        video_model_type=None,
        model="doubao-seedream-5-0-lite",
    )
    pricing = pricing_for(config)
    assert pricing["prices"] == {"2K": 0.22, "3K": 0.22, "4K": 0.22}
    assert "input_image" not in pricing


def test_pricing_for_video_model():
    config = SimpleNamespace(
        image_model_type=None,
        video_model_type="seedance_2",
        model="doubao-seedance-2-0",
    )
    pricing = pricing_for(config)
    assert pricing["type"] == "video"
    assert pricing["prices"]["720p"] == 46.00
    assert pricing["prices"]["4k"] == 26.00
    assert pricing["video_reference_prices"]["720p"] == 28.00


def test_pricing_for_minimax_h3_per_second_and_input_images():
    config = SimpleNamespace(
        image_model_type=None,
        video_model_type="minimax_h3",
        model="MiniMax-H3",
    )
    pricing = pricing_for(config)
    assert pricing["billing_unit"] == "second"
    assert pricing["prices"] == {"768P": 0.50, "2K": 0.80}
    assert pricing["video_reference_prices"] == {"768P": 0.50, "2K": 0.80}
    assert pricing["input_image"] == {"first_free": 5, "price_per_image": 0.20}


def test_wan3_pricing_starts_zero_until_admin_configures_contract_price():
    config = SimpleNamespace(
        image_model_type=None,
        video_model_type="wan_3",
        model="wan3.0-video",
    )
    pricing = pricing_for(config)
    assert pricing["billing_unit"] == "second"
    assert pricing["prices"] == {"480P": 0.0, "720P": 0.0, "1080P": 0.0}


def test_pricing_for_llm_model():
    config = SimpleNamespace(
        image_model_type=None,
        video_model_type=None,
        model="deepseek-v4-pro",
    )
    pricing = pricing_for(config)
    assert pricing["type"] == "text"
    assert pricing["input_price_per_1m"] == 12.00
    assert pricing["output_price_per_1m"] == 24.00


def test_pricing_for_unknown_model_returns_none():
    config = SimpleNamespace(
        image_model_type=None,
        video_model_type=None,
        model="some-unknown-model",
    )
    assert pricing_for(config) is None
