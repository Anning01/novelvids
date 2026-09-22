from decimal import Decimal

import pytest
from httpx import AsyncClient

from models.ai_task import AiTask
from models.config import AiModelConfig
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_billing_summary_endpoint(client: AsyncClient):
    novel = await Novel.create(name="计费小说", author="a")
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm", base_url="https://x", api_key="k", model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    )
    await ModelUsageRecord.create(
        novel_id=novel.id, task_type=AiTaskTypeEnum.extraction.value, billing_type="text",
        model_config_id=config.id, model_name="llm", model="m",
        usage={"input_tokens": 1500, "output_tokens": 500},
        cost=Decimal("0.002500"), status=TaskStatusEnum.completed.value,
    )

    response = await client.get("/api/billing/summary")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total_records"] == 1
    assert data["total_cost"] == 0.0025


@pytest.mark.asyncio
async def test_billing_projects_and_records(client: AsyncClient):
    novel = await Novel.create(name="项目甲", author="a")
    await ModelUsageRecord.create(
        novel_id=novel.id, task_type=AiTaskTypeEnum.video.value, billing_type="video",
        model="vid", usage={"seconds": 3, "resolution": "720p"},
        cost=Decimal("3.000000"), status=TaskStatusEnum.completed.value,
    )

    projects = await client.get("/api/billing/projects")
    assert projects.status_code == 200
    items = projects.json()["data"]["items"]
    assert items[0]["novel_name"] == "项目甲"
    assert items[0]["total_cost"] == 3.0

    records = await client.get(f"/api/billing/records?novel_id={novel.id}")
    assert records.status_code == 200
    assert records.json()["data"]["pagination"]["total"] == 1
    assert records.json()["data"]["items"][0]["billing_type"] == "video"


@pytest.mark.asyncio
async def test_billing_records_serializes_uuid_and_cost(client: AsyncClient):
    novel = await Novel.create(name="序列化测试", author="a")
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.completed.value,
        request_params={"novel_id": novel.id},
    )
    await ModelUsageRecord.create(
        novel_id=novel.id,
        task_type=AiTaskTypeEnum.extraction.value,
        billing_type="text",
        ai_task_id=task.id,
        model="m",
        usage={"input_tokens": 100},
        cost=Decimal("0.001000"),
        status=TaskStatusEnum.completed.value,
    )

    response = await client.get(f"/api/billing/records?novel_id={novel.id}")
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["ai_task_id"] == str(task.id)
    assert item["cost"] == 0.001


@pytest.mark.asyncio
async def test_agent_records_endpoint_groups_conversation_and_exposes_paged_details(client: AsyncClient):
    from models.creation_agent import AgentConversation
    from test.test_services.test_billing_conversation_records import agent_record
    novel = await Novel.create(name='对话成本')
    conversation = await AgentConversation.create(novel=novel)
    first = await agent_record(conversation, '0.1')
    await agent_record(conversation, '0.2')
    response = await client.get(f'/api/billing/records?novel_id={novel.id}&page_size=1')
    data = response.json()['data']
    assert data['pagination']['total'] == 1
    assert data['items'][0]['record_kind'] == 'agent_conversation'
    assert data['items'][0]['cost'] == 0.3 and data['items'][0]['turn_count'] == 2
    assert data['items'][0]['ai_task_id'] is None
    detail = await client.get(f'/api/billing/records/{first.id}/details?page_size=1&page=2')
    assert detail.json()['data']['pagination']['total'] == 2
    assert detail.json()['data']['items'][0]['id'] == first.id
    assert '私密会话' not in response.text + detail.text
