import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient

from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.ai_task import AiTask
from models.config import AiModelConfig
from services.ai_task_executor import ai_task_executor
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


# ---- Mock Handler ----

async def _mock_handler_execute(self, request_params: dict) -> dict:
    """Mock handler.execute: 直接写入 Scene 记录，跳过 OpenAI 调用。"""
    chapter_id = request_params["chapter_id"]

    s1 = await Scene.create(
        chapter_id=chapter_id,
        sequence=1,
        description="The Awakening",
        prompt="visual prose test 1",
        duration=4.0,
        metadata={
            "shot_title": "The Awakening",
            "api_metadata": {"model": "mock-model"},
            "token_usage": {"prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800},
            "request_duration": 1.23,
        },
    )
    s2 = await Scene.create(
        chapter_id=chapter_id,
        sequence=2,
        description="The Revelation",
        prompt="visual prose test 2",
        duration=8.0,
        metadata={
            "shot_title": "The Revelation",
            "api_metadata": {"model": "mock-model"},
            "token_usage": {"prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800},
            "request_duration": 1.23,
        },
    )

    return {
        "chapter_id": chapter_id,
        "scenes_created": 2,
        "scene_ids": [s1.id, s2.id],
        "total_shots": 2,
        "request_duration": 1.23,
        "token_usage": {"prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800},
    }


# ---- 辅助函数 ----

async def _setup_scene_env():
    """创建测试用的 novel、chapter、config。"""
    novel = await Novel.create(name="分镜测试小说", author="测试作者")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第1章 开始",
        content="张三身穿白袍走进了皇宫大殿，望着面前的龙椅陷入沉思。",
    )
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        name="test-storyboard",
        base_url="https://mock.api.com/v1",
        api_key="sk-test-mock",
        model="mock-model",
        is_active=True,
    )
    return novel, chapter, config


# =====================================================================
# CRUD API 测试
# =====================================================================

@pytest.mark.asyncio
async def test_api_create_scene(client: AsyncClient):
    """手动创建分镜。"""
    novel = await Novel.create(name="API Scene Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="Content"
    )

    payload = {
        "chapter_id": chapter.id,
        "sequence": 1,
        "prompt": "test prompt",
        "description": "Test Shot",
    }

    response = await client.post("/api/scene/", json=payload)
    assert response.status_code == 200, response.text

    # 验证 DB 写入
    scene = await Scene.get(chapter_id=chapter.id, sequence=1)
    assert scene.description == "Test Shot"
    assert scene.prompt == "test prompt"
    print(f"    POST /api/scene/ -> 200, 写入分镜 id={scene.id}, description='{scene.description}'")


@pytest.mark.asyncio
async def test_api_get_scene_detail(client: AsyncClient):
    """获取分镜详情。"""
    novel = await Novel.create(name="Detail Scene Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="Content"
    )
    scene = await Scene.create(
        chapter_id=chapter.id, sequence=1, description="Detail Shot", prompt="prompt"
    )

    response = await client.get(f"/api/scene/{scene.id}")
    assert response.status_code == 200, response.text
    print(f"    GET /api/scene/{scene.id} -> 200")


@pytest.mark.asyncio
async def test_api_update_scene(client: AsyncClient):
    """全量更新分镜。"""
    novel = await Novel.create(name="Update Scene Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="Content"
    )
    scene = await Scene.create(
        chapter_id=chapter.id, sequence=1, description="Old", prompt="old"
    )

    payload = {
        "chapter_id": chapter.id,
        "sequence": 1,
        "prompt": "updated prompt",
        "description": "Updated Shot",
    }

    response = await client.put(f"/api/scene/{scene.id}", json=payload)
    assert response.status_code == 200, response.text

    # 验证 DB 更新
    await scene.refresh_from_db()
    assert scene.description == "Updated Shot"
    assert scene.prompt == "updated prompt"
    print(f"    PUT /api/scene/{scene.id} -> 200, description='Old' -> 'Updated Shot', prompt='old' -> 'updated prompt'")


@pytest.mark.asyncio
async def test_api_patch_scene(client: AsyncClient):
    """局部更新分镜。"""
    novel = await Novel.create(name="Patch Scene Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="Content"
    )
    scene = await Scene.create(
        chapter_id=chapter.id, sequence=1, description="Original", prompt="original"
    )

    response = await client.patch(
        f"/api/scene/{scene.id}",
        json={"description": "Patched"},
    )
    assert response.status_code == 200, response.text

    # 验证 DB 局部更新
    await scene.refresh_from_db()
    assert scene.description == "Patched"
    assert scene.prompt == "original"  # 未改动
    print(f"    PATCH /api/scene/{scene.id} -> 200, description='Original' -> 'Patched', prompt 未变='original'")


@pytest.mark.asyncio
async def test_api_get_scene_list(client: AsyncClient):
    """获取分镜列表。"""
    novel = await Novel.create(name="List Scene Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="Content"
    )
    await Scene.create(chapter_id=chapter.id, sequence=1, description="S1", prompt="p1")
    await Scene.create(chapter_id=chapter.id, sequence=2, description="S2", prompt="p2")

    response = await client.get("/api/scene")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    total = data["pagination"]["total"]
    assert total >= 2
    print(f"    GET /api/scene -> 200, 列表总数={total}")


@pytest.mark.asyncio
async def test_api_delete_scene(client: AsyncClient):
    """删除分镜。"""
    novel = await Novel.create(name="Delete Scene Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="Content"
    )
    scene = await Scene.create(
        chapter_id=chapter.id, sequence=1, description="Delete", prompt="p"
    )
    scene_id = scene.id

    response = await client.delete(f"/api/scene/{scene_id}")
    assert response.status_code == 200, response.text

    exists = await Scene.filter(id=scene_id).exists()
    assert not exists
    print(f"    DELETE /api/scene/{scene_id} -> 200, 已确认不存在")


@pytest.mark.asyncio
async def test_api_get_nonexistent_scene(client: AsyncClient):
    """查询不存在的分镜返回 404。"""
    response = await client.get("/api/scene/99999")
    body = response.json()
    assert body["code"] == 404
    print(f"    GET /api/scene/99999 -> 404: {body['message']}")


# =====================================================================
# AI 生成分镜 API 测试 (Mock handler.execute)
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.storyboard.handler.StoryboardTaskHandler.execute",
    new=_mock_handler_execute,
)
async def test_generate_creates_task_and_scenes(client: AsyncClient):
    """生成接口：创建任务 + BackgroundTask 写入分镜。"""
    novel, chapter, config = await _setup_scene_env()

    response = await client.post(
        "/api/scene/generate/",
        json={"chapter_id": chapter.id, "model": 1},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["task_type"] == AiTaskTypeEnum.storyboard.value
    assert data["status"] == TaskStatusEnum.pending.value
    task_id = data["id"]
    print(f"    POST /api/scene/generate/ -> 200, 任务已提交 id={task_id}, status=pending")

    # 手动执行任务（BackgroundTask 在测试中不会自动运行）
    task = await AiTask.get(id=task_id)
    await ai_task_executor.run(task)

    # 验证任务完成
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value
    assert task.response_data is not None
    assert task.response_data["scenes_created"] == 2
    assert task.response_data["token_usage"]["total_tokens"] == 800
    print(f"    任务执行完成: status=completed, 创建分镜数={task.response_data['scenes_created']}, token消耗={task.response_data['token_usage']['total_tokens']}")

    # 验证分镜写入
    scenes = await Scene.filter(chapter_id=chapter.id).order_by("sequence")
    assert len(scenes) == 2
    assert scenes[0].description == "The Awakening"
    assert scenes[0].sequence == 1
    assert scenes[0].duration == 4.0
    assert scenes[1].description == "The Revelation"
    assert scenes[1].sequence == 2
    assert scenes[1].duration == 8.0

    # 验证 metadata 包含 token 使用信息
    assert scenes[0].metadata["token_usage"]["total_tokens"] == 800
    assert scenes[0].metadata["api_metadata"]["model"] == "mock-model"
    assert scenes[0].metadata["request_duration"] == 1.23
    print(f"    分镜验证: [{scenes[0].sequence}] '{scenes[0].description}' {scenes[0].duration}s, [{scenes[1].sequence}] '{scenes[1].description}' {scenes[1].duration}s")
    print(f"    元数据验证: model={scenes[0].metadata['api_metadata']['model']}, tokens={scenes[0].metadata['token_usage']['total_tokens']}, duration={scenes[0].metadata['request_duration']}s")


@pytest.mark.asyncio
async def test_generate_duplicate_blocked(client: AsyncClient):
    """重复提交同一章节的生成任务被拦截。"""
    novel, chapter, config = await _setup_scene_env()

    # 创建一个 pending 的任务
    existing = await AiTask.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": chapter.id},
    )

    response = await client.post(
        "/api/scene/generate/",
        json={"chapter_id": chapter.id, "model": 1},
    )
    body = response.json()
    assert body["code"] == 400
    assert "进行中" in body["message"]
    print(f"    已有任务 id={existing.id}，重复提交被拦截: {body['message']}")


@pytest.mark.asyncio
async def test_generate_no_config(client: AsyncClient):
    """无启用的配置时返回 404。"""
    novel = await Novel.create(name="No Config Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Ch1", content="content"
    )

    response = await client.post(
        "/api/scene/generate/",
        json={"chapter_id": chapter.id, "model": 1},
    )
    body = response.json()
    assert body["code"] == 404
    print(f"    无配置，返回 404: {body['message']}")


@pytest.mark.asyncio
@patch(
    "services.storyboard.handler.StoryboardTaskHandler.execute",
    new=_mock_handler_execute,
)
async def test_generate_stale_task_cleaned(client: AsyncClient):
    """超时异常任务被清理后可重新提交。"""
    from datetime import datetime, timezone, timedelta

    novel, chapter, config = await _setup_scene_env()

    # 创建超时的 running 任务
    stale_task = await AiTask.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": chapter.id},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )

    # 提交新任务应先清理超时任务再通过
    response = await client.post(
        "/api/scene/generate/",
        json={"chapter_id": chapter.id, "model": 1},
    )
    assert response.status_code == 200, response.text

    # 旧任务应被标记为 failed
    await stale_task.refresh_from_db()
    assert stale_task.status == TaskStatusEnum.failed.value
    assert "异常任务清理" in stale_task.error_message
    print(f"    超时任务 id={stale_task.id} 已清理: '{stale_task.error_message}'")
    print(f"    新任务提交成功: {response.json()['data']['id']}")


@pytest.mark.asyncio
@patch(
    "services.storyboard.handler.StoryboardTaskHandler.execute",
    side_effect=Exception("LLM API error"),
)
async def test_generate_llm_failure_marks_task_failed(mock_exec, client: AsyncClient):
    """LLM 调用失败时任务标记为 failed。"""
    novel, chapter, config = await _setup_scene_env()

    resp = await client.post(
        "/api/scene/generate/",
        json={"chapter_id": chapter.id, "model": 1},
    )
    task = await AiTask.get(id=resp.json()["data"]["id"])
    await ai_task_executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert "LLM API error" in task.error_message
    print(f"    任务 id={task.id} 执行失败: status=failed, error='{task.error_message}'")
