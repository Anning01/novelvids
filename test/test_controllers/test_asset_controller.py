import pytest
from fastapi import HTTPException

from controllers.asset import asset_controller
from models.novel import Novel
from models.asset import Asset
from schemas.asset import AssetCreate, AssetUpdate, AssetPatch
from utils.enums import AssetTypeEnum
from utils.page import QueryParams


# =====================================================================
# 基础 CRUD
# =====================================================================

@pytest.mark.asyncio
async def test_创建资产():
    """直接通过控制器创建资产。"""
    novel = await Novel.create(name="Asset Test Novel", author="Author")
    obj_in = AssetCreate(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
        aliases=["小张"],
        description="主角",
        base_traits="young man, calm",
    )
    asset = await asset_controller.create(obj_in)
    assert asset.canonical_name == "张三"
    assert asset.aliases == ["小张"]


@pytest.mark.asyncio
async def test_查询资产():
    """通过 ID 查询资产。"""
    novel = await Novel.create(name="Get Asset Novel", author="Author")
    created = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="大殿",
    )

    result = await asset_controller.get(created.id)
    assert result.id == created.id
    assert result.canonical_name == "大殿"


@pytest.mark.asyncio
async def test_查询不存在的资产_抛出404():
    """查询不存在的 ID 应抛出 404。"""
    with pytest.raises(Exception):
        await asset_controller.get(99999)


@pytest.mark.asyncio
async def test_全量更新资产():
    """全量更新资产字段。"""
    novel = await Novel.create(name="Update Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="旧名",
        description="旧描述",
    )

    obj_in = AssetUpdate(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="新名",
        description="新描述",
    )
    result = await asset_controller.update(asset.id, obj_in)
    assert result.canonical_name == "新名"
    assert result.description == "新描述"


@pytest.mark.asyncio
async def test_局部更新资产():
    """只更新 description，其他不变。"""
    novel = await Novel.create(name="Patch Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="原始名",
        description="原始描述",
    )

    obj_in = AssetPatch(description="更新后的描述")
    result = await asset_controller.patch(asset.id, obj_in)
    assert result.description == "更新后的描述"
    assert result.canonical_name == "原始名"  # 未改动


@pytest.mark.asyncio
async def test_删除资产():
    """删除资产后数据库中不再存在。"""
    novel = await Novel.create(name="Delete Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="待删除",
    )

    await asset_controller.remove(asset.id)
    exists = await Asset.filter(id=asset.id).exists()
    assert not exists


# =====================================================================
# 列表查询
# =====================================================================

@pytest.mark.asyncio
async def test_列表查询_无过滤():
    """不带任何过滤条件查询列表。"""
    novel = await Novel.create(name="List Novel", author="Author")
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="人物A",
    )
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="场景A",
    )

    from schemas.asset import AssetBriefOut
    params = QueryParams(page=1, page_size=10, filters={})
    result = await asset_controller.list(params, AssetBriefOut)
    assert result["pagination"]["total"] == 2
    assert len(result["items"]) == 2


@pytest.mark.asyncio
async def test_列表查询_无效chapter_id被忽略():
    """传入无效 chapter_id（非数字），应被忽略，正常返回全部结果。"""
    novel = await Novel.create(name="Filter Novel", author="Author")
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="人物B",
    )

    from schemas.asset import AssetBriefOut
    params = QueryParams(page=1, page_size=10, filters={"chapter_id": "abc"})
    result = await asset_controller.list(params, AssetBriefOut)
    # 无效 chapter_id 被忽略，返回全部
    assert result["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_列表查询_分页():
    """分页参数生效。"""
    novel = await Novel.create(name="Paging Novel", author="Author")
    for i in range(5):
        await Asset.create(
            novel_id=novel.id,
            asset_type=AssetTypeEnum.person.value,
            canonical_name=f"人物-{i}",
        )

    from schemas.asset import AssetBriefOut
    params = QueryParams(page=1, page_size=2, filters={})
    result = await asset_controller.list(params, AssetBriefOut)
    assert result["pagination"]["total"] == 5
    assert len(result["items"]) == 2
    assert result["pagination"]["pages"] == 3


@pytest.mark.asyncio
async def test_列表查询_按类型过滤():
    """通过 asset_type 过滤。"""
    novel = await Novel.create(name="Type Filter Novel", author="Author")
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="人物",
    )
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="场景",
    )

    from schemas.asset import AssetBriefOut
    params = QueryParams(
        page=1, page_size=10,
        filters={"asset_type": str(AssetTypeEnum.person.value)},
    )
    result = await asset_controller.list(params, AssetBriefOut)
    assert result["pagination"]["total"] == 1
    assert result["items"][0].canonical_name == "人物"


@pytest.mark.asyncio
async def test_列表查询_按chapter_id过滤():
    """通过 chapter_id 过滤 source_chapters JSON 数组。"""
    novel = await Novel.create(name="Chapter Filter Novel", author="Author")
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="出场人物",
        source_chapters=[1, 3, 5],
    )
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="未出场人物",
        source_chapters=[2, 4],
    )

    from schemas.asset import AssetBriefOut
    params = QueryParams(page=1, page_size=10, filters={"chapter_id": "3"})
    result = await asset_controller.list(params, AssetBriefOut)
    assert result["pagination"]["total"] == 1
    assert result["items"][0].canonical_name == "出场人物"
    print(f"    按 chapter_id=3 过滤: 命中资产='{result['items'][0].canonical_name}'")


# =====================================================================
# reference 参考图生成
# =====================================================================

@pytest.mark.asyncio
async def test_reference_提交参考图任务():
    """reference 方法成功提交参考图生成任务。"""
    from models.config import AiModelConfig
    from models.ai_task import AiTask
    from utils.enums import AiTaskTypeEnum, TaskStatusEnum

    novel = await Novel.create(name="Ref Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="参考图测试人物",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="test-ref",
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )

    task = await asset_controller.reference(asset.id)

    assert task.id is not None
    assert task.task_type == AiTaskTypeEnum.reference_image.value
    assert task.status == TaskStatusEnum.pending.value
    assert task.request_params["asset_id"] == asset.id
    assert task.request_params["novel_id"] == novel.id
    print(f"    提交参考图任务 id={task.id}, asset_id={asset.id}, status=pending")


@pytest.mark.asyncio
async def test_reference_重复提交被拦截():
    """同一资产重复提交参考图任务被拦截。"""
    from models.config import AiModelConfig
    from models.ai_task import AiTask
    from utils.enums import AiTaskTypeEnum, TaskStatusEnum

    novel = await Novel.create(name="Dup Ref Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="重复提交测试",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="test-ref-dup",
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )

    # 创建一个 pending 的任务
    existing = await AiTask.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        status=TaskStatusEnum.pending.value,
        request_params={"asset_id": asset.id},
    )

    with pytest.raises(HTTPException) as exc_info:
        await asset_controller.reference(asset.id)
    assert exc_info.value.status_code == 400
    assert "进行中" in exc_info.value.detail
    print(f"    已有任务 id={existing.id}，重复提交被拦截: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_reference_无配置报404():
    """无启用的参考图配置时报 404。"""
    novel = await Novel.create(name="No Config Ref Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="无配置测试",
    )

    with pytest.raises(HTTPException) as exc_info:
        await asset_controller.reference(asset.id)
    assert exc_info.value.status_code == 404
    print(f"    无配置，返回 404: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_reference_超时任务被清理后可重新提交():
    """超时任务被清理后可重新提交参考图任务。"""
    from datetime import datetime, timezone, timedelta
    from models.config import AiModelConfig
    from models.ai_task import AiTask
    from utils.enums import AiTaskTypeEnum, TaskStatusEnum

    novel = await Novel.create(name="Stale Ref Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="超时清理测试",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="test-ref-stale",
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )

    # 创建超时的 running 任务
    stale_task = await AiTask.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        status=TaskStatusEnum.running.value,
        request_params={"asset_id": asset.id},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )

    task = await asset_controller.reference(asset.id)
    assert task.id is not None

    await stale_task.refresh_from_db()
    assert stale_task.status == TaskStatusEnum.failed.value
    print(f"    超时任务 id={stale_task.id} 已清理, 新任务 id={task.id} 提交成功")
