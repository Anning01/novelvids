import pytest

from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_usage_record_creates_and_defaults():
    record = await ModelUsageRecord.create(
        novel_id=1,
        task_type=AiTaskTypeEnum.storyboard.value,
        billing_type="text",
        model="deepseek-chat",
        status=TaskStatusEnum.completed.value,
    )
    assert record.id is not None
    assert record.usage == {}
    assert record.currency == "CNY"
    assert record.cost == 0
    assert record.model_name is None
    assert record.pricing_snapshot is None


@pytest.mark.asyncio
async def test_ai_model_config_pricing_field_roundtrips():
    pricing = {"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0}
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="priced-llm",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="deepseek-chat",
        pricing=pricing,
    )
    assert config.pricing == pricing
