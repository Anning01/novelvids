import pytest
from fastapi import HTTPException

from services.image_generation.capabilities import validate_selection


def test_seedream_pro_selection_maps_schema_values_to_exact_provider_size():
    selection = validate_selection(
        "seedream_5_pro",
        clarity="1.5K",
        aspect_ratio="21:9",
        output_format="jpeg",
        generation_count=1,
    )
    assert selection.provider_size == "2352x1008"
    assert selection.output_format == "jpeg"
    assert selection.generation_count == 1


def test_seedream_lite_rejects_clarity_from_another_model_type():
    with pytest.raises(HTTPException, match="清晰度"):
        validate_selection(
            "seedream_5_lite",
            clarity="1K",
            aspect_ratio="16:9",
            output_format="png",
            generation_count=1,
        )


def test_gpt_image_2_uses_quality_and_supported_three_way_size_mapping():
    selection = validate_selection(
        "gpt_image_2",
        clarity="high",
        aspect_ratio="3:2",
        output_format="webp",
        generation_count=1,
    )
    assert selection.provider_quality == "high"
    assert selection.provider_size == "1536x1024"
    assert selection.output_format == "webp"


def test_image_generation_rejects_more_than_one_image():
    with pytest.raises(HTTPException, match="生成数量"):
        validate_selection(
            "gpt_image_2",
            clarity="medium",
            aspect_ratio="1:1",
            output_format="png",
            generation_count=2,
        )
