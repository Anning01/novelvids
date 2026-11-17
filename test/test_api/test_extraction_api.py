"""Public extraction API, task lifecycle and current structured-output execution."""
import pytest
from httpx import AsyncClient
from models.novel import Novel
from models.chapter import Chapter
from models.asset import Asset
from models.ai_task import AiTask
from models.config import AiModelConfig
from services.ai_task_executor import ai_task_executor
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, AssetTypeEnum


async def _setup_extraction_env():
    """创建测试用的 novel、chapter、config。"""
    novel = await Novel.create(
        name="提取测试小说",
        author="测试作者",
        content="测试内容",
    )
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第1章 开始",
        content="张三身穿白袍走进了皇宫大殿，手持尚方宝剑。李四阴沉地站在一旁。",
    )
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="test-model",
        base_url="https://mock.api.com/v1",
        api_key="sk-test-mock",
        model="mock-model",
        is_active=True,
        concurrency=3,
    )
    return novel, chapter, config



@pytest.mark.asyncio
async def test_extract_duplicate_task_reuses_existing(client: AsyncClient, configured_creation_agent):
    """重复提交同一章节的提取任务返回原任务。"""
    novel, chapter, config = await _setup_extraction_env()

    # 创建一个 pending 的任务
    existing = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": chapter.id, "novel_id": novel.id},
    )

    # 再次提交复用已有任务
    response = await client.post(f"/api/chapter/extract/{chapter.id}")
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["id"] == str(existing.id)



@pytest.mark.asyncio
async def test_get_latest_extraction_task_for_chapter(client: AsyncClient):
    """设定页可以恢复当前章节最近一次提取任务状态。"""
    novel, chapter, config = await _setup_extraction_env()
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": chapter.id, "novel_id": novel.id},
    )
    await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.completed.value,
        request_params={"chapter_id": chapter.id + 1, "novel_id": novel.id},
    )

    response = await client.get(f"/api/chapter/extract/{chapter.id}/latest")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == str(task.id)
    assert data["status"] == TaskStatusEnum.running.value



@pytest.mark.asyncio
async def test_get_latest_extraction_task_returns_none_when_missing(client: AsyncClient):
    """从未提取过的章节返回空任务。"""
    novel, chapter, config = await _setup_extraction_env()

    response = await client.get(f"/api/chapter/extract/{chapter.id}/latest")

    assert response.status_code == 200, response.text
    assert response.json()["data"] is None



@pytest.mark.asyncio
async def test_extract_stale_task_cleaned(client: AsyncClient, configured_creation_agent):
    """超时异常任务被清理后可重新提交。"""
    from datetime import datetime, timezone, timedelta

    novel, chapter, config = await _setup_extraction_env()

    # 创建一个「看起来超时」的 running 任务
    stale_task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": chapter.id, "novel_id": novel.id},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=700),
    )

    # 提交新任务 - 应先清理超时任务再通过
    response = await client.post(f"/api/chapter/extract/{chapter.id}")
    assert response.status_code == 200, response.text

    # 旧任务应被标记为 failed
    await stale_task.refresh_from_db()
    assert stale_task.status == TaskStatusEnum.failed.value
    assert "Stale task expired" in stale_task.error_message



@pytest.mark.asyncio
async def test_extract_without_assistant_returns_422(client: AsyncClient):
    """未配置严格 JSON Schema 模型时，按 422 契约阻止新任务。"""
    novel = await Novel.create(name="No Config Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="content"
    )

    response = await client.post(f"/api/chapter/extract/{chapter.id}")
    body = response.json()
    assert body["code"] == 422
    assert "json schema" in body["message"].lower()

    assert await AiTask.filter(task_type=AiTaskTypeEnum.extraction.value).count() == 0



@pytest.mark.asyncio
async def test_cancel_task(client: AsyncClient):
    """取消任务。"""
    novel, chapter, config = await _setup_extraction_env()

    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": chapter.id},
    )

    response = await client.post(f"/api/task/{task.id}/cancel")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == TaskStatusEnum.cancelled.value



@pytest.mark.asyncio
async def test_query_task_status(client: AsyncClient):
    """查询任务状态。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": 1},
    )

    response = await client.get(f"/api/task/{task.id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == TaskStatusEnum.running.value
    assert data["task_type"] == AiTaskTypeEnum.extraction.value



@pytest.mark.asyncio
async def test_get_nonexistent_task(client: AsyncClient):
    """查询不存在的任务返回 404。"""
    import uuid
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/task/{fake_id}")
    body = response.json()
    assert body["code"] == 404



@pytest.mark.asyncio
async def test_cancel_completed_task_rejected(client: AsyncClient):
    """已完成的任务不可取消。"""
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.completed.value,
        request_params={"chapter_id": 1},
    )

    response = await client.post(f"/api/task/{task.id}/cancel")
    body = response.json()
    assert body["code"] == 400
    assert "Cannot cancel" in body["message"]



@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_real_extraction(client: AsyncClient, test_env: dict):
    """使用真实 LLM API 测试提取。"""
    base_url = test_env.get("EXTRACTION_BASE_URL")
    api_key = test_env.get("EXTRACTION_API_KEY")
    model = test_env.get("EXTRACTION_MODEL")

    if not all([base_url, api_key, model]):
        pytest.skip("test/.test.env 未配置 EXTRACTION_* 参数")

    novel = await Novel.create(
        name="真实提取测试",
        author="测试作者",
    )
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第1章 先抄一批家再说",
        content=(
            "张凡从梦中惊醒，发现自己穿越成了崇祯皇帝。"
            "他望着镜中苍白消瘦的面容，身穿白色丝绸睡袍，不敢相信眼前的一切。"
            "太监王承恩端着一碗药走了进来，恭敬地跪在地上。"
            "桌上放着一把金色龙纹尚方宝剑。"
        ),
    )
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.creation_agent.value,
        supports_strict_output=True,
        supports_json_output=True,
        name="real-test",
        base_url=base_url,
        api_key=api_key,
        model=model,
        is_active=True,
        concurrency=3,
    )

    # 提交并执行
    resp = await client.post(f"/api/chapter/extract/{chapter.id}")
    assert resp.status_code == 200, resp.text
    task = await AiTask.get(id=resp.json()["data"]["id"])
    await ai_task_executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value, (
        f"任务失败: {task.error_message}"
    )

    # 验证资产已写入
    assets = await Asset.filter(novel_id=novel.id)
    assert len(assets) > 0


@pytest.mark.asyncio
async def test_extraction_api_reuses_identity_across_chapters(client, configured_creation_agent, monkeypatch):
    from test.test_services.test_strict_text_tasks import mock_model
    from test.test_services.test_strict_production import asset_payload
    from models.config import GeneralConfig
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': 'zh'})
    novel, first, _ = await _setup_extraction_env()
    second = await Chapter.create(novel=novel, number=2, name='第二章', content='阿岚再次出现。')
    requests = mock_model(monkeypatch, asset_payload())
    for chapter in (first, second):
        response = await client.post(f'/api/chapter/extract/{chapter.id}')
        assert response.status_code == 200, response.text
        task = await AiTask.get(id=response.json()['data']['id'])
        assert task.request_params['output_contract']['name'] == 'assets'
        await ai_task_executor.run(task)
        await task.refresh_from_db()
        assert task.status == 3, task.error_message
    asset = await Asset.get(novel=novel)
    assert asset.source_chapters == [1, 2]
    assert len(requests) == 2
