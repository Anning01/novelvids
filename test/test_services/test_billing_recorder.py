from decimal import Decimal

import pytest

from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.billing.recorder import billing_recorder
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_record_text_snapshots_pricing_and_cost():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm",
        base_url="https://api.example.com",
        api_key="sk",
        model="deepseek-chat",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    )
    record = await billing_recorder.record_text(
        novel_id=7,
        task_type=AiTaskTypeEnum.extraction.value,
        model_config_id=config.id,
        token_usage={"prompt_tokens": 1500, "completion_tokens": 500},
        status=TaskStatusEnum.completed.value,
    )
    assert record is not None
    assert record.billing_type == "text"
    assert record.model_config_id == config.id
    assert record.model_name == "llm"
    assert record.model == "deepseek-chat"
    assert record.pricing_snapshot == config.pricing
    assert record.cost == Decimal("0.002500")


@pytest.mark.asyncio
async def test_record_image_only_bills_on_provided_count():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image",
        base_url="https://ark.example.com/api/v3",
        api_key="sk",
        model="img",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_pro",
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.10}},
    )
    record = await billing_recorder.record_image(
        novel_id=7,
        task_type=AiTaskTypeEnum.reference_image.value,
        model_config_id=config.id,
        image_count=3,
        clarity="1K",
        status=TaskStatusEnum.completed.value,
    )
    assert record.billing_type == "image"
    assert record.cost == Decimal("0.300000")
    assert record.model_type == "seedream_5_pro"


@pytest.mark.asyncio
async def test_record_video_uses_video_task_type_and_cost():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="sk",
        model="vid",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        pricing={"type": "video", "currency": "CNY", "prices": {"720p": 1.0}},
    )
    record = await billing_recorder.record_video(
        novel_id=7,
        model_config_id=config.id,
        seconds=6.0,
        resolution="720p",
        status=TaskStatusEnum.completed.value,
        video_id=11,
    )
    assert record.billing_type == "video"
    assert record.task_type == AiTaskTypeEnum.video.value
    assert record.video_id == 11
    assert record.cost == Decimal("6.000000")


@pytest.mark.asyncio
async def test_record_missing_config_writes_zero_cost_snapshot_none():
    record = await billing_recorder.record_text(
        novel_id=7,
        task_type=AiTaskTypeEnum.extraction.value,
        model_config_id=999999,
        fallback_model="ghost-model",
        token_usage={"prompt_tokens": 100},
        status=TaskStatusEnum.failed.value,
    )
    assert record is not None
    assert record.pricing_snapshot is None
    assert record.model == "ghost-model"
    assert record.cost == Decimal("0")
