import pytest

from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from services.scene_asset_backfill import backfill_scene_assets
from utils.enums import AssetTypeEnum


async def _make_asset(novel_id: int, name: str, asset_type: AssetTypeEnum) -> Asset:
    return await Asset.create(
        novel_id=novel_id,
        asset_type=asset_type.value,
        canonical_name=name,
        aliases=[],
    )


@pytest.mark.asyncio
async def test_backfill_links_referenced_assets_and_is_idempotent():
    novel = await Novel.create(name="回填测试")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第一章", content="正文")
    person = await _make_asset(novel.id, "张三", AssetTypeEnum.person)
    item = await _make_asset(novel.id, "旧钥匙", AssetTypeEnum.item)

    scene = await Scene.create(
        chapter_id=chapter.id,
        sequence=1,
        description="夜访",
        prompt="【镜头描述】@{张三} 推门而入。",
        duration=4,
    )

    stats = await backfill_scene_assets()

    assert stats["scenes"] == 1
    assert stats["updated_scenes"] == 1
    assert stats["linked_assets"] == 1

    await scene.fetch_related("assets")
    linked_ids = {asset.id for asset in scene.assets}
    assert linked_ids == {person.id}

    # 幂等：重复执行不重复补链
    again = await backfill_scene_assets()
    assert again["updated_scenes"] == 0
    assert again["linked_assets"] == 0

    await scene.fetch_related("assets")
    assert {asset.id for asset in scene.assets} == {person.id}


@pytest.mark.asyncio
async def test_backfill_matches_alias_and_skips_plain_text():
    novel = await Novel.create(name="别名测试")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第一章", content="正文")
    person = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="郊区小楼",
        aliases=["小楼"],
    )
    scene = await Scene.create(
        chapter_id=chapter.id,
        sequence=1,
        prompt="他走向 @{小楼}。",
        duration=4,
    )

    stats = await backfill_scene_assets()
    assert stats["linked_assets"] == 1

    await scene.fetch_related("assets")
    assert {asset.id for asset in scene.assets} == {person.id}


@pytest.mark.asyncio
async def test_backfill_skips_plain_text_without_binding_syntax():
    novel = await Novel.create(name="纯文本测试")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第一章", content="正文")
    await _make_asset(novel.id, "张三", AssetTypeEnum.person)
    scene = await Scene.create(
        chapter_id=chapter.id,
        sequence=1,
        prompt="张三推门而入。",
        duration=4,
    )

    stats = await backfill_scene_assets()
    assert stats["linked_assets"] == 0

    await scene.fetch_related("assets")
    assert list(scene.assets) == []
