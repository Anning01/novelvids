from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest
from tortoise import Tortoise

from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from services.extraction.context import (
    ChapterExtractionInput,
    ExtractionContext,
    ExtractionContextLoader,
    KnownAssetSnapshot,
    NovelExtractionMetadata,
    normalize_source_chapters,
)
from utils.enums import AssetTypeEnum


@pytest.fixture
async def extraction_project():
    novel = await Novel.create(
        name="厄运之手",
        author="陈默",
        description="一部都市异能故事。",
        tags=["都市异能", "复仇"],
        story_outline="宫平获得能力并反抗压迫。",
        project_type="短剧",
        project_setting="现代都市。",
    )
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="能力觉醒",
        content="宫平在蓝都保健中心外看见一辆黑色自行车。",
    )
    second_chapter = await Chapter.create(
        novel_id=novel.id,
        number=2,
        name="反击开始",
        content="宫平开始反抗。",
    )
    # Deliberately create types out of their required query order.
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.item.value,
        canonical_name="黑色自行车",
        aliases=["自行车"],
        description="停在门口的自行车",
        base_traits="black bicycle",
        source_chapters=["9", second_chapter.number],
        metadata={"reference_layout": 5, "internal_note": "private"},
    )
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="蓝都保健中心",
        aliases=[],
        description="压迫宫平的工作场所",
        base_traits="modern wellness center",
        source_chapters=[chapter.number],
        metadata={"role": 2, "ignored": "private"},
    )
    gong_ping = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        aliases=["宫先生"],
        description="获得能力的员工",
        base_traits="young Chinese man",
        source_chapters=[chapter.number],
        metadata={
            "role": "主角",
            "reference_layout": "character_turnaround",
            "internal_note": "must not leak",
        },
        main_image="/private/宫平.png",
    )
    lin_qing = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="林青",
        aliases=["小林"],
        description="宫平的同事",
        base_traits="young Chinese woman",
        source_chapters=[chapter.number],
        metadata={"role": "同事", "internal_note": "must not leak"},
    )
    return novel, chapter, second_chapter, gong_ping.id, lin_qing.id


@pytest.mark.asyncio
async def test_loader_returns_immutable_project_wide_extraction_context(
    extraction_project,
):
    novel, chapter, _, gong_ping_id, lin_qing_id = extraction_project

    context = await ExtractionContextLoader().load(
        novel_id=novel.id,
        chapter_id=chapter.id,
    )

    assert context.novel.name == "厄运之手"
    assert context.novel.tags == ("都市异能", "复仇")
    assert context.novel.story_outline == "宫平获得能力并反抗压迫。"
    assert context.chapter.number == 1
    assert context.chapter.content == chapter.content
    assert tuple(asset.canonical_name for asset in context.assets) == (
        "宫平",
        "林青",
        "蓝都保健中心",
        "黑色自行车",
    )
    assert tuple(asset.asset_type_name for asset in context.assets) == (
        "人物",
        "人物",
        "场景",
        "物品",
    )
    assert tuple(asset.id for asset in context.assets[:2]) == (
        gong_ping_id,
        lin_qing_id,
    )
    assert context.assets[0].metadata == {
        "role": "主角",
        "reference_layout": "character_turnaround",
    }
    assert context.assets[1].metadata == {"role": "同事"}
    assert context.assets[2].metadata == {"role": "2"}
    assert context.assets[3].metadata == {"reference_layout": "5"}
    assert context.assets[3].source_chapters == (2, 9)
    assert isinstance(context.assets[0].metadata, MappingProxyType)
    with pytest.raises(TypeError):
        context.assets[0].metadata["role"] = "反派"
    for asset in context.assets:
        for absent_field in (
            "main_image",
            "angle_image_1",
            "angle_image_2",
            "image_source",
            "is_global",
            "last_updated_chapter",
            "novel",
            "novel_id",
            "save",
        ):
            assert not hasattr(asset, absent_field)


@pytest.mark.asyncio
async def test_loader_excludes_non_extractable_asset_types():
    novel = await Novel.create(name="资产类型过滤小说")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="类型过滤。",
    )
    for asset_type, name in (
        (AssetTypeEnum.person, "人物资产"),
        (AssetTypeEnum.scene, "场景资产"),
        (AssetTypeEnum.item, "道具资产"),
        (AssetTypeEnum.product, "商品资产"),
        (AssetTypeEnum.style, "风格资产"),
    ):
        await Asset.create(
            novel_id=novel.id,
            asset_type=asset_type.value,
            canonical_name=name,
        )

    context = await ExtractionContextLoader().load(
        novel_id=novel.id,
        chapter_id=chapter.id,
    )

    assert tuple(asset.canonical_name for asset in context.assets) == (
        "人物资产",
        "场景资产",
        "道具资产",
    )


@pytest.mark.asyncio
async def test_loader_normalizes_nullable_json_snapshot_fields():
    novel = await Novel.create(name="空元数据小说", tags=None)
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="空元数据。",
    )
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="空别名人物",
        aliases=[],
        source_chapters=["10", 2, "1"],
        metadata={},
    )

    context = await ExtractionContextLoader().load(
        novel_id=novel.id,
        chapter_id=chapter.id,
    )

    assert context.novel.tags == ()
    assert context.assets[0].source_chapters == (1, 2, 10)
    # The current schema rejects SQL NULL for these fields, but historical rows
    # can still be materialized with null JSON values. Exercise that loader path
    # against a real ORM model instance without trying to persist invalid data.
    asset.aliases = None
    asset.metadata = None
    asset.source_chapters = None
    snapshot = ExtractionContextLoader._asset_snapshot(asset)
    assert snapshot.aliases == ()
    assert snapshot.metadata == {}
    assert snapshot.source_chapters == ()


@pytest.mark.asyncio
async def test_loader_ignores_invalid_historical_source_chapters():
    novel = await Novel.create(name="历史章节值小说")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="历史数据兼容。",
    )
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="历史人物",
        source_chapters=[
            None,
            True,
            False,
            "invalid",
            "10",
            2,
            2.9,
            6.0,
            "2",
            "7.0",
            "",
            4,
            4,
            float("nan"),
            float("inf"),
            float("-inf"),
        ],
    )

    context = await ExtractionContextLoader().load(
        novel_id=novel.id,
        chapter_id=chapter.id,
    )

    assert context.assets[0].source_chapters == (2, 4, 6, 10)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10", (10,)),
        ("2.0", ()),
        (10, (10,)),
        (True, ()),
        (False, ()),
        (2.0, (2,)),
        (2.9, ()),
        (float("nan"), ()),
        (float("inf"), ()),
        (float("-inf"), ()),
        (None, ()),
        ({"10": True}, ()),
        (object(), ()),
    ],
)
def test_normalize_source_chapters_handles_scalar_and_invalid_objects(
    value,
    expected,
):
    assert normalize_source_chapters(value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored_json",
    ['"10"', "10"],
    ids=["string-scalar", "number-scalar"],
)
async def test_loader_normalizes_real_orm_scalar_source_chapters(stored_json):
    novel = await Novel.create(name=f"标量章节小说-{stored_json}")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="标量章节兼容。",
    )
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="标量章节人物",
        source_chapters=[],
    )
    connection = Tortoise.get_connection("default")
    await connection.execute_query(
        'UPDATE "assets" SET "source_chapters" = ? WHERE "id" = ?',
        [stored_json, asset.id],
    )

    context = await ExtractionContextLoader().load(
        novel_id=novel.id,
        chapter_id=chapter.id,
    )

    assert context.assets[0].source_chapters == (10,)
    assert 0 not in context.assets[0].source_chapters
    assert 1 not in context.assets[0].source_chapters


@pytest.mark.asyncio
async def test_loader_treats_non_mapping_historical_metadata_as_empty():
    novel = await Novel.create(name="历史元数据小说")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="历史元数据兼容。",
    )
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="列表元数据",
        metadata=["legacy", {"role": "不应暴露"}],
    )
    string_metadata_asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="字符串元数据",
        metadata={},
    )

    context = await ExtractionContextLoader().load(
        novel_id=novel.id,
        chapter_id=chapter.id,
    )

    assert context.assets[0].metadata == {}
    # The JSON field rejects a scalar string during writes, but historical rows
    # can still materialize one. Exercise that loader boundary on a real model.
    string_metadata_asset.metadata = "legacy-metadata"
    assert ExtractionContextLoader._asset_snapshot(string_metadata_asset).metadata == {}


@pytest.mark.asyncio
async def test_loader_snapshots_are_frozen(extraction_project):
    novel, chapter, *_ = extraction_project
    context = await ExtractionContextLoader().load(
        novel_id=novel.id,
        chapter_id=chapter.id,
    )

    with pytest.raises(FrozenInstanceError):
        context.novel.name = "改名"
    with pytest.raises(FrozenInstanceError):
        context.assets[0].canonical_name = "改名"
    with pytest.raises(FrozenInstanceError):
        context.chapter.number = 2
    with pytest.raises(FrozenInstanceError):
        context.chapter = ChapterExtractionInput(
            id=context.chapter.id,
            number=context.chapter.number,
            name=context.chapter.name,
            content=context.chapter.content,
        )

    assert isinstance(context, ExtractionContext)
    assert isinstance(context.novel, NovelExtractionMetadata)
    assert isinstance(context.assets[0], KnownAssetSnapshot)
    assert isinstance(context.chapter, ChapterExtractionInput)


@pytest.mark.asyncio
async def test_loader_rejects_chapter_from_another_novel(extraction_project):
    _, chapter, *_ = extraction_project
    other_novel = await Novel.create(name="另一部小说")

    with pytest.raises(ValueError, match="不属于小说"):
        await ExtractionContextLoader().load(
            novel_id=other_novel.id,
            chapter_id=chapter.id,
        )
