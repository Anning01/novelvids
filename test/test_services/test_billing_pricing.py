from decimal import Decimal

import pytest

from services.billing.pricing import (
    compute_image_cost,
    compute_input_image_cost,
    compute_text_cost,
    compute_video_cost,
    normalize_token_usage,
)

TEXT_PRICING = {
    "type": "text",
    "currency": "CNY",
    "input_price_per_1m": 1.0,
    "output_price_per_1m": 2.0,
}
IMAGE_PRICING = {"type": "image", "currency": "CNY", "prices": {"1K": 0.10, "2K": 0.20}}
VIDEO_PRICING = {
    "type": "video",
    "currency": "CNY",
    "prices": {"480p": 46.0, "720p": 46.0, "1080p": 51.0, "4k": 26.0},
}


def test_normalize_token_usage_prompt_completion_keys():
    usage = {"prompt_tokens": 1500, "completion_tokens": 500, "total_tokens": 2000}
    assert normalize_token_usage(usage) == {"input_tokens": 1500, "output_tokens": 500}


def test_normalize_token_usage_new_keys_and_empty():
    assert normalize_token_usage({"input_tokens": 10, "output_tokens": 20}) == {
        "input_tokens": 10,
        "output_tokens": 20,
    }
    assert normalize_token_usage(None) == {"input_tokens": 0, "output_tokens": 0}
    assert normalize_token_usage({}) == {"input_tokens": 0, "output_tokens": 0}


def test_compute_text_cost_rounds_to_six_decimals():
    usage = {"prompt_tokens": 1500, "completion_tokens": 500}
    # 1500/1e6*1 + 500/1e6*2 = 0.0015 + 0.001 = 0.0025
    assert compute_text_cost(usage, TEXT_PRICING) == Decimal("0.002500")


def test_compute_text_cost_missing_pricing_is_zero():
    assert compute_text_cost({"prompt_tokens": 100}, None) == Decimal("0")
    assert compute_text_cost({}, {"type": "image", "prices": {}}) == Decimal("0")


def test_compute_image_cost_multiplies_count_by_tier():
    assert compute_image_cost(3, "1K", IMAGE_PRICING) == Decimal("0.300000")
    assert compute_image_cost(1, "2K", IMAGE_PRICING) == Decimal("0.200000")


def test_compute_image_cost_missing_tier_is_zero():
    assert compute_image_cost(3, "4K", IMAGE_PRICING) == Decimal("0")
    assert compute_image_cost(3, "1K", None) == Decimal("0")


def test_compute_video_cost_token_based():
    # 720p: 21600 token/s × 5s = 108000 tokens；46 × 108000 / 1e6 = 4.968
    assert compute_video_cost(5.0, "720p", VIDEO_PRICING) == Decimal("4.968000")
    # 4k: 194400 token/s × 5s = 972000；26 × 972000 / 1e6 = 25.272
    assert compute_video_cost(5.0, "4k", VIDEO_PRICING) == Decimal("25.272000")


def test_compute_video_cost_missing_resolution_is_zero():
    assert compute_video_cost(5.0, "8k", VIDEO_PRICING) == Decimal("0")
    assert compute_video_cost(5.0, "720p", None) == Decimal("0")


def test_compute_input_image_cost_first_free_then_per_image():
    pricing = {
        "type": "image",
        "currency": "CNY",
        "prices": {"1K": 0.3},
        "input_image": {"first_free": 1, "price_per_image": 0.02},
    }
    assert compute_input_image_cost(0, pricing) == Decimal("0")
    assert compute_input_image_cost(1, pricing) == Decimal("0")
    assert compute_input_image_cost(2, pricing) == Decimal("0.020000")
    assert compute_input_image_cost(5, pricing) == Decimal("0.080000")


def test_compute_input_image_cost_missing_fee_is_zero():
    assert compute_input_image_cost(5, {"type": "image", "prices": {"1K": 0.3}}) == Decimal("0")
    assert compute_input_image_cost(5, None) == Decimal("0")


def test_compute_video_cost_uses_video_reference_prices():
    pricing = {
        "type": "video",
        "currency": "CNY",
        "prices": {"720p": 46.0},
        "video_reference_prices": {"720p": 28.0},
    }
    assert compute_video_cost(5.0, "720p", pricing, has_video_reference=False) == Decimal("4.968000")
    # 含视频 3 秒：28 × 21600 × (5+3) / 1e6 = 4.8384
    assert compute_video_cost(
        5.0, "720p", pricing, input_video_seconds=3.0, has_video_reference=True
    ) == Decimal("4.838400")


def test_compute_video_cost_video_reference_falls_back_to_prices():
    pricing = {"type": "video", "currency": "CNY", "prices": {"720p": 46.0}}
    assert compute_video_cost(5.0, "720p", pricing, has_video_reference=True) == Decimal("4.968000")


def test_compute_cost_applies_discount():
    text_pricing = {
        "type": "text", "currency": "CNY",
        "input_price_per_1m": 1.0, "output_price_per_1m": 2.0, "discount": 0.9,
    }
    usage = {"prompt_tokens": 1500, "completion_tokens": 500}
    # 无折扣 0.0025；0.9 折 = 0.00225
    assert compute_text_cost(usage, text_pricing) == Decimal("0.002250")

    image_pricing = {"type": "image", "currency": "CNY", "prices": {"1K": 0.30}, "discount": 0.9}
    assert compute_image_cost(2, "1K", image_pricing) == Decimal("0.540000")

    video_pricing = {"type": "video", "currency": "CNY", "prices": {"720p": 46.0}, "discount": 0.9}
    # 46 × 21600 × 5 / 1e6 = 4.968；× 0.9 = 4.4712
    assert compute_video_cost(5.0, "720p", video_pricing) == Decimal("4.471200")


def test_compute_cost_multiplier_over_one():
    image_pricing = {"type": "image", "currency": "CNY", "prices": {"1K": 0.30}, "discount": 1.5}
    assert compute_image_cost(1, "1K", image_pricing) == Decimal("0.450000")


def test_compute_cost_no_discount_is_unchanged():
    image_pricing = {"type": "image", "currency": "CNY", "prices": {"1K": 0.30}}
    assert compute_image_cost(1, "1K", image_pricing) == Decimal("0.300000")
