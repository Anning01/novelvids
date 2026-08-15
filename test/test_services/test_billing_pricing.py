from decimal import Decimal

import pytest

from services.billing.pricing import (
    compute_image_cost,
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
VIDEO_PRICING = {"type": "video", "currency": "CNY", "prices": {"480p": 0.50, "720p": 1.00}}


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


def test_compute_video_cost_multiplies_seconds_by_resolution():
    assert compute_video_cost(6.0, "720p", VIDEO_PRICING) == Decimal("6.000000")
    assert compute_video_cost(10.5, "480p", VIDEO_PRICING) == Decimal("5.250000")


def test_compute_video_cost_missing_resolution_is_zero():
    assert compute_video_cost(6.0, "4k", VIDEO_PRICING) == Decimal("0")
    assert compute_video_cost(6.0, "720p", None) == Decimal("0")
