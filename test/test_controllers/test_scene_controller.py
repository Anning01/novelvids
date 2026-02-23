import pytest
from controllers.scene import scene_controller
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.ai_task import AiTask
from models.config import AiModelConfig
from schemas.scene import SceneCreate, SceneUpdate
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


# ---- 辅助函数 ----

async def _create_chapter() -> tuple[Novel, Chapter]:
    novel = await Novel.create(name="场景测试小说", author="测试作者")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="第1章", content="测试内容"
    )
    return novel, chapter


async def _create_scene(chapter: Chapter, sequence: int = 1) -> Scene:
    scene_in = SceneCreate(
        chapter_id=chapter.id,
        sequence=sequence,
        prompt="test prompt",
        description="Test Shot",
    )
    return await scene_controller.create(scene_in)


# =====================================================================
# CRUD 测试
# =====================================================================

@pytest.mark.asyncio
async def test_create_scene(sql_profiler):
    """创建分镜。"""
    _, chapter = await _create_chapter()
    scene_in = SceneCreate(
        chapter_id=chapter.id,
        sequence=1,
        prompt="visual prose test",
        description="The Revelation",
    )

    async with sql_profiler as p:
        scene = await scene_controller.create(scene_in)

    assert scene.id is not None
    assert scene.sequence == 1
    assert scene.description == "The Revelation"
    assert scene.prompt == "visual prose test"
    assert p.query_count > 0
    print(f"    创建分镜 id={scene.id}, sequence={scene.sequence}, SQL查询数={p.query_count}")


@pytest.mark.asyncio
async def test_get_scene():
    """获取分镜详情。"""
    _, chapter = await _create_chapter()
    scene = await _create_scene(chapter)

    fetched = await scene_controller.get(scene.id)
    assert fetched.id == scene.id
    assert fetched.description == "Test Shot"
    print(f"    获取分镜 id={fetched.id}, description='{fetched.description}'")


@pytest.mark.asyncio
async def test_update_scene():
    """全量更新分镜。"""
    _, chapter = await _create_chapter()
    scene = await _create_scene(chapter)

    update_data = SceneUpdate(
        chapter_id=chapter.id,
        sequence=1,
        prompt="updated prompt",
        description="Updated Shot",
    )

    updated = await scene_controller.update(scene.id, update_data)
    assert updated.description == "Updated Shot"
    assert updated.prompt == "updated prompt"
    print(f"    全量更新: description '{scene.description}' -> '{updated.description}', prompt '{scene.prompt}' -> '{updated.prompt}'")


@pytest.mark.asyncio
async def test_patch_scene():
    """局部更新分镜。"""
    _, chapter = await _create_chapter()
    scene = await _create_scene(chapter)

    from schemas.scene import ScenePatch
    patch_data = ScenePatch(description="Patched Shot")

    patched = await scene_controller.patch(scene.id, patch_data)
    assert patched.description == "Patched Shot"
    assert patched.prompt == "test prompt"  # 未改动
    print(f"    局部更新: description '{scene.description}' -> '{patched.description}', prompt 未变='{patched.prompt}'")


@pytest.mark.asyncio
async def test_delete_scene():
    """删除分镜。"""
    _, chapter = await _create_chapter()
    scene = await _create_scene(chapter)
    scene_id = scene.id

    await scene_controller.remove(scene_id)
    exists = await Scene.filter(id=scene_id).exists()
    assert not exists
    print(f"    删除分镜 id={scene_id}, 已确认不存在")


@pytest.mark.asyncio
async def test_get_with_assets():
    """_get_with_assets 预加载关联资产。"""
    from models.asset import Asset
    from utils.enums import AssetTypeEnum

    novel, chapter = await _create_chapter()
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    scene = await _create_scene(chapter)
    await scene.assets.add(asset)

    result = await scene_controller._get_with_assets(scene.id)
    assets = list(result.assets)
    assert len(assets) == 1
    assert assets[0].canonical_name == "张三"
    print(f"    _get_with_assets: 分镜 id={result.id}, 关联资产={[a.canonical_name for a in assets]}")


# =====================================================================
# generate 任务提交测试
# =====================================================================

@pytest.mark.asyncio
async def test_generate_submits_task():
    """generate 方法成功提交分镜生成任务。"""
    _, chapter = await _create_chapter()
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        name="test-storyboard",
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )

    task = await scene_controller.generate(chapter.id)

    assert task.id is not None
    assert task.task_type == AiTaskTypeEnum.storyboard.value
    assert task.status == TaskStatusEnum.pending.value
    assert task.request_params["chapter_id"] == chapter.id
    print(f"    提交任务 id={task.id}, type=storyboard, status=pending, chapter_id={chapter.id}")


@pytest.mark.asyncio
async def test_generate_duplicate_blocked():
    """同一章节重复提交被拦截。"""
    _, chapter = await _create_chapter()
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        name="test-storyboard",
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )

    # 创建一个 pending 的任务
    existing = await AiTask.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": chapter.id},
    )

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await scene_controller.generate(chapter.id)
    assert exc_info.value.status_code == 400
    assert "进行中" in exc_info.value.detail
    print(f"    已有任务 id={existing.id}，重复提交被拦截: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_generate_no_config():
    """无启用配置时报错。"""
    _, chapter = await _create_chapter()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await scene_controller.generate(chapter.id)
    assert exc_info.value.status_code == 404
    print(f"    无配置，返回 404: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_generate_stale_task_cleaned():
    """超时任务被清理后可重新提交。"""
    from datetime import datetime, timezone, timedelta

    _, chapter = await _create_chapter()
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        name="test-storyboard",
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )

    # 创建超时的 running 任务
    stale_task = await AiTask.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": chapter.id},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )

    # 提交新任务应成功（超时任务被清理）
    task = await scene_controller.generate(chapter.id)
    assert task.id is not None

    # 旧任务应被标记为 failed
    await stale_task.refresh_from_db()
    assert stale_task.status == TaskStatusEnum.failed.value
    print(f"    超时任务 id={stale_task.id} 已清理(status=failed)，新任务 id={task.id} 提交成功")
