import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient

from models.novel import Novel
from models.chapter import Chapter
from models.asset import Asset
from models.ai_task import AiTask
from models.config import AiModelConfig
from services.ai_task_executor import ai_task_executor
from services.extraction.handler import ExtractionTaskHandler
from services.extraction.extractor import PersonList, SceneList, ItemList, Person, Scene, Item
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, AssetTypeEnum


# ---- Mock 数据 ----

MOCK_PERSONS = PersonList(persons=[
    Person(
        name="张三",
        aliases=["小张", "张哥"],
        description="主角，沉稳冷静",
        base_traits="young man, calm expression, black hair, medium build",
        appearances=[],
    ),
    Person(
        name="李四",
        aliases=[],
        description="反派，阴险狡诈",
        base_traits="tall man, sharp eyes, scar on left cheek",
        appearances=[],
    ),
])

MOCK_SCENES = SceneList(scenes=[
    Scene(
        name="皇宫大殿",
        aliases=["金銮殿"],
        description="辉煌壮丽的皇宫正殿",
        base_traits="grand palace hall, golden pillars, red carpet, dragon throne",
        appearances=[],
    ),
])

MOCK_ITEMS = ItemList(items=[
    Item(
        name="尚方宝剑",
        aliases=["天子剑"],
        description="皇帝御赐宝剑",
        base_traits="golden sword with dragon engravings, jeweled hilt",
        appearances=[],
    ),
])


async def _mock_extract(self, text, chapter_number):
    """根据提取器类型返回对应的 mock 数据。"""
    if self.response_model == PersonList:
        return MOCK_PERSONS
    elif self.response_model == SceneList:
        return MOCK_SCENES
    elif self.response_model == ItemList:
        return MOCK_ITEMS


# ---- 辅助函数 ----

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


# =====================================================================
# Mock 测试
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_extract_creates_task_and_assets(client: AsyncClient):
    """提取接口：创建任务 + BackgroundTask 写入资产。"""
    novel, chapter, config = await _setup_extraction_env()

    # 调用提取接口
    response = await client.post(f"/api/chapter/extract/{chapter.id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["task_type"] == AiTaskTypeEnum.extraction.value
    assert data["status"] == TaskStatusEnum.pending.value
    task_id = data["id"]

    # 手动执行任务（BackgroundTask 在测试中不会自动运行）
    task = await AiTask.get(id=task_id)
    await ai_task_executor.run(task)

    # 验证任务完成
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value
    assert task.response_data is not None

    # 验证资产写入
    persons = await Asset.filter(novel_id=novel.id, asset_type=AssetTypeEnum.person.value)
    assert len(persons) == 2
    assert {p.canonical_name for p in persons} == {"张三", "李四"}

    scenes = await Asset.filter(novel_id=novel.id, asset_type=AssetTypeEnum.scene.value)
    assert len(scenes) == 1
    assert scenes[0].canonical_name == "皇宫大殿"

    items = await Asset.filter(novel_id=novel.id, asset_type=AssetTypeEnum.item.value)
    assert len(items) == 1
    assert items[0].canonical_name == "尚方宝剑"


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_extract_incremental_merge(client: AsyncClient):
    """增量提取：第二次提取合并别名和章节。"""
    novel, chapter1, config = await _setup_extraction_env()

    # 第一次提取
    resp = await client.post(f"/api/chapter/extract/{chapter1.id}")
    task1 = await AiTask.get(id=resp.json()["data"]["id"])
    await ai_task_executor.run(task1)

    # 创建第二章
    chapter2 = await Chapter.create(
        novel_id=novel.id,
        number=2,
        name="第2章 发展",
        content="张三再次出现在大殿中。",
    )

    # 第二次提取
    resp2 = await client.post(f"/api/chapter/extract/{chapter2.id}")
    task2 = await AiTask.get(id=resp2.json()["data"]["id"])
    await ai_task_executor.run(task2)

    # 张三应该只有一条记录，source_chapters 包含 [1, 2]
    person = await Asset.get(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    assert 1 in person.source_chapters
    assert 2 in person.source_chapters
    assert person.last_updated_chapter == 2


@pytest.mark.asyncio
async def test_extract_duplicate_task_blocked(client: AsyncClient):
    """重复提交同一章节的提取任务被拦截。"""
    novel, chapter, config = await _setup_extraction_env()

    # 创建一个 pending 的任务
    await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": chapter.id, "novel_id": novel.id},
    )

    # 再次提交应被拒绝
    response = await client.post(f"/api/chapter/extract/{chapter.id}")
    body = response.json()
    assert body["code"] == 400
    assert "进行中" in body["message"]


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_extract_stale_task_cleaned(client: AsyncClient):
    """超时异常任务被清理后可重新提交。"""
    from datetime import datetime, timezone, timedelta

    novel, chapter, config = await _setup_extraction_env()

    # 创建一个「看起来超时」的 running 任务
    stale_task = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": chapter.id, "novel_id": novel.id},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )

    # 提交新任务 - 应先清理超时任务再通过
    response = await client.post(f"/api/chapter/extract/{chapter.id}")
    assert response.status_code == 200, response.text

    # 旧任务应被标记为 failed
    await stale_task.refresh_from_db()
    assert stale_task.status == TaskStatusEnum.failed.value
    assert "异常任务清理" in stale_task.error_message


@pytest.mark.asyncio
async def test_extract_no_config_returns_404(client: AsyncClient):
    """无启用的配置时返回 404。"""
    novel = await Novel.create(name="No Config Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="content"
    )

    response = await client.post(f"/api/chapter/extract/{chapter.id}")
    body = response.json()
    assert body["code"] == 404
    assert "未配置" in body["message"]


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    side_effect=Exception("LLM API error"),
)
async def test_extract_llm_failure_marks_task_failed(mock_extract, client: AsyncClient):
    """LLM 调用失败时任务标记为 failed。"""
    novel, chapter, config = await _setup_extraction_env()

    resp = await client.post(f"/api/chapter/extract/{chapter.id}")
    task = await AiTask.get(id=resp.json()["data"]["id"])
    await ai_task_executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert "LLM API error" in task.error_message


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
    assert "不可取消" in body["message"]


# =====================================================================
# 真实 LLM 测试（需配置 test/.test.env，使用 pytest -m real_llm 运行）
# =====================================================================

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
        task_type=AiTaskTypeEnum.extraction.value,
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
    print(f"\n[Real LLM] 提取到 {len(assets)} 个资产:")
    for a in assets:
        print(f"  [{AssetTypeEnum(a.asset_type).nickname}] {a.canonical_name}: {a.base_traits}")
