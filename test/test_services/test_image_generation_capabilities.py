import pytest
from fastapi import HTTPException

from services.image_generation.capabilities import validate_selection


GPT_IMAGE_MODELS = ("gpt_image_2", "gpt_image_2_5", "gpt_image_2_6", "gpt_image_2_6_sunburst", "gpt_image_2_6_flare")


@pytest.mark.parametrize("model_type", GPT_IMAGE_MODELS)
@pytest.mark.parametrize("clarity,size", [("1K", "1024x1024"), ("2K", "2048x2048"), ("4K", "4096x4096")])
def test_gpt_image_models_use_resolution_with_fixed_high_quality(model_type, clarity, size):
    selection = validate_selection(model_type, clarity=clarity, aspect_ratio="1:1",
        output_format="png", generation_count=1)
    assert selection.provider_size == size
    assert selection.provider_quality == "high"
    assert selection.clarity == clarity


@pytest.mark.parametrize("clarity", ["1.5K", "3K", "8K"])
def test_gpt_image_models_reject_other_quality_tiers(clarity):
    with pytest.raises(HTTPException, match="清晰度"):
        validate_selection("gpt_image_2_6", clarity=clarity, aspect_ratio="16:9",
            output_format="png", generation_count=1)


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


@pytest.mark.parametrize("legacy_clarity", ["low", "medium", "high"])
def test_gpt_image_2_legacy_quality_uses_default_resolution_and_high_quality(legacy_clarity):
    selection = validate_selection(
        "gpt_image_2",
        clarity=legacy_clarity,
        aspect_ratio="1:1",
        output_format="webp",
        generation_count=1,
    )
    assert selection.provider_quality == "high"
    assert selection.clarity == "1K"
    assert selection.provider_size == "1024x1024"
    assert selection.output_format == "webp"


def test_image_generation_rejects_more_than_one_image():
    with pytest.raises(HTTPException, match="生成数量"):
        validate_selection(
            "gpt_image_2",
            clarity="1K",
            aspect_ratio="1:1",
            output_format="png",
            generation_count=2,
        )
