from decimal import Decimal

import pytest

from models.config import AiModelConfig
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services.billing import aggregation
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.page import QueryParams


async def _seed():
    novel_a = await Novel.create(name="项目A", author="a")
    novel_b = await Novel.create(name="项目B", author="b")
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm", base_url="https://x", api_key="k", model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    )
    await ModelUsageRecord.create(
        novel_id=novel_a.id, task_type=AiTaskTypeEnum.extraction.value, billing_type="text",
        model_config_id=config.id, model_name="llm", model="m",
        pricing_snapshot=config.pricing, usage={"input_tokens": 1500, "output_tokens": 500},
        cost=Decimal("0.002500"), status=TaskStatusEnum.completed.value,
    )
    await ModelUsageRecord.create(
        novel_id=novel_a.id, task_type=AiTaskTypeEnum.storyboard.value, billing_type="text",
        model_config_id=config.id, model_name="llm", model="m",
        pricing_snapshot=config.pricing, usage={"input_tokens": 0, "output_tokens": 0},
        cost=Decimal("0.001000"), status=TaskStatusEnum.completed.value,
    )
    await ModelUsageRecord.create(
        novel_id=novel_b.id, task_type=AiTaskTypeEnum.video.value, billing_type="video",
        model="vid", usage={"seconds": 3, "resolution": "720p"},
        cost=Decimal("3.000000"), status=TaskStatusEnum.completed.value,
    )
    return novel_a, novel_b


@pytest.mark.asyncio
async def test_summary_aggregates_total_and_dimensions():
    await _seed()
    result = await aggregation.summary()
    assert result["total_records"] == 3
    assert round(result["total_cost"], 6) == 3.0035
    billing = {item["billing_type"]: item["cost"] for item in result["by_billing_type"]}
    assert billing["text"] == 0.0035
    assert billing["video"] == 3.0


@pytest.mark.asyncio
async def test_project_costs_groups_and_sorts():
    novel_a, novel_b = await _seed()
    result = await aggregation.project_costs(1, 10)
    items = result["items"]
    assert result["pagination"]["total"] == 2
    assert items[0]["novel_id"] == novel_b.id  # 3.0 > 0.0035
    assert items[0]["novel_name"] == "项目B"


@pytest.mark.asyncio
async def test_project_detail_returns_novel_cost():
    novel_a, _ = await _seed()
    result = await aggregation.project_detail(novel_a.id)
    assert result["novel_name"] == "项目A"
    assert result["record_count"] == 2
    assert round(result["total_cost"], 6) == 0.0035


@pytest.mark.asyncio
async def test_list_records_filters_by_novel():
    novel_a, novel_b = await _seed()
    params = QueryParams(page=1, page_size=10, filters={"novel_id": novel_a.id})
    result = await aggregation.list_records(params)
    assert result["pagination"]["total"] == 2
    assert all(item.novel_id == novel_a.id for item in result["items"])
