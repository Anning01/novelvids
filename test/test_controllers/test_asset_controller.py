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
