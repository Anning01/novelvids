from types import SimpleNamespace
from decimal import Decimal

import pytest

from models.ai_task import AiTask
from models.config import AiModelConfig
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services.billing.recorder import record_ai_task_usage
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


async def _config():
    return await AiModelConfig.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        task_types=[AiTaskTypeEnum.remake_decomposition.value],
        name="重制理解模型",
        base_url="https://example.test/v1",
        api_key="secret",
        model="vision-model",
        is_active=True,
        pricing={
            "type": "text",
            "currency": "CNY",
            "input_price_per_1m": 1.0,
            "output_price_per_1m": 2.0,
        },
    )


@pytest.mark.asyncio
async def test_completed_remake_task_bills_aggregate_video_analysis_tokens_from_result():
    novel = await Novel.create(name="重制计费", author="tester")
    config = await _config()
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.completed.value,
        request_params={"novel_id": novel.id},
    )

    await record_ai_task_usage(
        task,
        result={
            "llm_config_id": config.id,
            "llm_model": config.model,
            "token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
            },
        },
    )

    record = await ModelUsageRecord.get(ai_task_id=task.id)
    assert record.task_type == AiTaskTypeEnum.remake_decomposition.value
    assert record.model_config_id == config.id
    assert record.usage == {"input_tokens": 1000, "output_tokens": 500}
    assert record.cost == Decimal("0.002000")


@pytest.mark.asyncio
async def test_failed_remake_task_bills_consumed_retry_tokens_from_safe_error():
    novel = await Novel.create(name="重制失败计费", author="tester")
    config = await _config()
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.failed.value,
        request_params={
            "novel_id": novel.id,
            "model_config_id": config.id,
            "model": config.model,
        },
    )
    error = SimpleNamespace(
        usage={"prompt_tokens": 300, "completion_tokens": 50, "total_tokens": 350}
    )

    await record_ai_task_usage(task, result=None, error=error)

    record = await ModelUsageRecord.get(ai_task_id=task.id)
    assert record.model_config_id == config.id
    assert record.status == TaskStatusEnum.failed.value
    assert record.usage == {"input_tokens": 300, "output_tokens": 50}
