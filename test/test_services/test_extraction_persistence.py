from unittest.mock import AsyncMock, patch

import pytest
from tortoise import Tortoise

from models.asset import Asset
from models.novel import Novel
from services.extraction.extractor import (
    AssetExtractionResult,
    Item,
    Person,
    Scene,
)
from services.extraction.persistence import AssetUpsertService
from utils.enums import AssetTypeEnum


PERSON_TRAITS = """时代基底: modern
国家/朝代: China
人种: Chinese
类型基底: realistic
脸型: oval face, calm dark eyes
发型: short black hair
耳饰: does not wear earrings
身材: medium height, lean build
头身比: realistic seven-and-a-half-head proportion
上身着装: charcoal cotton jacket
下身着装: straight black trousers
鞋子: brown leather shoes
性别: male
年龄: young adult"""

UPDATED_PERSON_TRAITS = """时代基底: modern
国家/朝代: China
人种: Chinese
类型基底: realistic
脸型: angular face, focused dark eyes
发型: short black hair
耳饰: does not wear earrings
身材: tall, lean build
头身比: realistic eight-head proportion
上身着装: navy cotton jacket
下身着装: straight black trousers
鞋子: black leather shoes
性别: male
年龄: young adult"""


def _person(
    *,
    name: str = "宫平",
    aliases: list[str] | None = None,
    description: str = "本章明确出现的人物",
    base_traits: str = PERSON_TRAITS,
) -> Person:
    return Person(
        name=name,
        aliases=aliases or [],
        description=description,
        base_traits=base_traits,
    )


def _result(
    *,
    persons: list[Person] | None = None,
    scenes: list[Scene] | None = None,
    items: list[Item] | None = None,
) -> AssetExtractionResult:
    return AssetExtractionResult(
        persons=persons or [],
        scenes=scenes or [],
        items=items or [],
    )


@pytest.mark.asyncio
async def test_保存结果返回三类资产摘要():
    novel = await Novel.create(name="事务保存小说")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        aliases=["宫先生"],
        description="旧描述",
        base_traits=PERSON_TRAITS,
        source_chapters=[1],
        last_updated_chapter=1,
    )
    result = _result(
        persons=[_person(aliases=["宫先生"])],
        scenes=[
            Scene(
                name="办公室",
                aliases=[],
                description="公司办公室",
                base_traits="modern office, fluorescent ceiling lights",
            )
        ],
        items=[
            Item(
                name="黑色自行车",
                aliases=[],
                description="宫平的通勤工具",
                base_traits="black steel commuter bicycle",
            )
        ],
    )

    summary = await AssetUpsertService().save_result(
        novel_id=novel.id,
        chapter_number=1,
        result=result,
    )

    assert summary == {
        "persons": [{"name": "宫平", "action": "updated"}],
        "scenes": [{"name": "办公室", "action": "created"}],
        "items": [{"name": "黑色自行车", "action": "created"}],
    }


@pytest.mark.asyncio
async def test_增量提取_合并别名和章节():
    novel = await Novel.create(name="章节合并小说")
    service = AssetUpsertService()

    await service.save_result(
        novel_id=novel.id,
        chapter_number=1,
        result=_result(persons=[_person(aliases=["宫先生"])]),
    )
    summary = await service.save_result(
        novel_id=novel.id,
        chapter_number=2,
        result=_result(persons=[_person(aliases=["小宫"])]),
    )

    assert summary["persons"] == [{"name": "宫平", "action": "updated"}]
    persons = await Asset.filter(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
    )
    assert len(persons) == 1
    assert persons[0].source_chapters == [1, 2]
    assert persons[0].last_updated_chapter == 2
    assert persons[0].aliases == ["宫先生", "小宫"]


@pytest.mark.asyncio
async def test_增量提取_宽容规范化历史来源章节():
    novel = await Novel.create(name="历史来源章节小说")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        source_chapters=["9", 2, None, "bad"],
        last_updated_chapter=2,
    )

    await AssetUpsertService().save_result(
        novel_id=novel.id,
        chapter_number=3,
        result=_result(persons=[_person()]),
    )
    await existing.refresh_from_db()

    assert existing.source_chapters == [2, 3, 9]


@pytest.mark.asyncio
async def test_增量提取_伪章节不会持久化():
    novel = await Novel.create(name="伪章节清理小说")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        source_chapters=[
            True,
            False,
            2.9,
            float("nan"),
            float("inf"),
            float("-inf"),
            4.0,
            "5",
            "6.0",
        ],
        last_updated_chapter=5,
    )

    await AssetUpsertService().save_result(
        novel_id=novel.id,
        chapter_number=7,
        result=_result(persons=[_person()]),
    )
    await existing.refresh_from_db()

    assert existing.source_chapters == [4, 5, 7]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored_json",
    ['"10"', "10"],
    ids=["string-scalar", "number-scalar"],
)
async def test_增量提取_真实ORM标量来源章节按单值合并(stored_json):
    novel = await Novel.create(name=f"ORM 标量来源章节-{stored_json}")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        source_chapters=[],
        last_updated_chapter=2,
    )
    connection = Tortoise.get_connection("default")
    await connection.execute_query(
        'UPDATE "assets" SET "source_chapters" = ? WHERE "id" = ?',
        [stored_json, existing.id],
    )

    await AssetUpsertService().save_result(
        novel_id=novel.id,
        chapter_number=3,
        result=_result(persons=[_person()]),
    )
    await existing.refresh_from_db()

    assert existing.source_chapters == [3, 10]
    assert 0 not in existing.source_chapters
    assert 1 not in existing.source_chapters


@pytest.mark.asyncio
async def test_增量提取_同一章节重复提取不重复追加():
    novel = await Novel.create(name="重复提取小说")
    service = AssetUpsertService()
    result = _result(persons=[_person()])

    await service.save_result(novel_id=novel.id, chapter_number=1, result=result)
    await service.save_result(novel_id=novel.id, chapter_number=1, result=result)

    person = await Asset.get(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
    )
    assert person.source_chapters == [1]


@pytest.mark.asyncio
async def test_增量提取_别名命中且空字段不覆盖旧资料():
    novel = await Novel.create(name="别名合并小说")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李火旺",
        aliases=["红中"],
        description="保留的旧描述",
        base_traits="保留的旧视觉资料",
        main_image="/media/li-huowang.png",
        source_chapters=[1],
        last_updated_chapter=1,
    )

    summary = await AssetUpsertService().save_result(
        novel_id=novel.id,
        chapter_number=9,
        result=_result(
            persons=[
                _person(
                    name="红中",
                    aliases=["李兄"],
                    description="",
                    base_traits="",
                )
            ]
        ),
    )
    await existing.refresh_from_db()

    assert summary["persons"] == [{"name": "红中", "action": "updated"}]
    assert await Asset.filter(novel=novel).count() == 1
    assert existing.description == "保留的旧描述"
    assert existing.base_traits == "保留的旧视觉资料"
    assert existing.main_image == "/media/li-huowang.png"
    assert existing.source_chapters == [1, 9]
    assert set(existing.aliases) == {"红中", "李兄"}


@pytest.mark.asyncio
async def test_增量提取_较早章节重跑不会回滚较新资料():
    novel = await Novel.create(name="状态机防回滚")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.item.value,
        canonical_name="桃木牌",
        aliases=["洞窟铭牌"],
        description="第八十八章确认的完整新资料",
        base_traits="完整的新形态",
        source_chapters=[88],
        last_updated_chapter=88,
    )

    await AssetUpsertService().save_result(
        novel_id=novel.id,
        chapter_number=1,
        result=_result(
            items=[
                Item(
                    name="洞窟铭牌",
                    aliases=[],
                    description="第一章的早期旧资料",
                    base_traits="旧形态",
                )
            ]
        ),
    )
    await existing.refresh_from_db()

    assert existing.description == "第八十八章确认的完整新资料"
    assert existing.base_traits == "完整的新形态"
    assert existing.source_chapters == [1, 88]
    assert existing.last_updated_chapter == 88


@pytest.mark.asyncio
async def test_正式提取覆盖项目分析的临时人物描述():
    novel = await Novel.create(name="临时视觉资料升级")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="云薇子",
        aliases=[],
        description="项目分析生成的人物小传",
        base_traits="气质优雅的年轻女性，长发飘飘，常穿素雅连衣裙。",
        source_chapters=[236, 239, 240],
        last_updated_chapter=240,
        metadata={
            "role": "关键人物",
            "analysis_source": "project_analysis",
        },
    )

    await AssetUpsertService().save_result(
        novel_id=novel.id,
        chapter_number=236,
        result=_result(
            persons=[
                _person(
                    name="云薇子",
                    description="本章明确出现的人物",
                    base_traits=UPDATED_PERSON_TRAITS,
                )
            ]
        ),
    )
    await existing.refresh_from_db()

    assert existing.base_traits == UPDATED_PERSON_TRAITS
    assert existing.description == "本章明确出现的人物"
    assert existing.last_updated_chapter == 236
    assert existing.metadata["role"] == "关键人物"
    assert existing.metadata["reference_layout"] == "character_turnaround"
    assert "analysis_source" not in existing.metadata


@pytest.mark.asyncio
async def test_增量提取_合并别名去重():
    novel = await Novel.create(name="别名去重小说")
    service = AssetUpsertService()
    result = _result(persons=[_person(aliases=["宫先生", "宫先生"])])

    await service.save_result(novel_id=novel.id, chapter_number=1, result=result)
    await service.save_result(novel_id=novel.id, chapter_number=2, result=result)

    person = await Asset.get(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
    )
    assert person.aliases == ["宫先生"]


@pytest.mark.asyncio
async def test_后续分类保存失败时回滚先前分类更新():
    novel = await Novel.create(name="事务回滚小说")
    original = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        aliases=["宫先生"],
        description="事务前描述",
        base_traits=PERSON_TRAITS,
        source_chapters=[7],
        last_updated_chapter=7,
    )
    original_count = await Asset.filter(novel=novel).count()
    original_traits = original.base_traits
    original_source_chapters = list(original.source_chapters)
    result = _result(
        persons=[
            _person(
                aliases=["小宫"],
                description="事务中更新",
                base_traits=UPDATED_PERSON_TRAITS,
            )
        ],
        scenes=[
            Scene(
                name="办公室",
                aliases=[],
                description="触发创建失败",
                base_traits="modern office",
            )
        ],
    )
    service = AssetUpsertService()

    with patch(
        "services.extraction.persistence.Asset.create",
        new=AsyncMock(side_effect=RuntimeError("forced save failure")),
    ):
        with pytest.raises(RuntimeError, match="forced save failure"):
            await service.save_result(
                novel_id=novel.id,
                chapter_number=9,
                result=result,
            )

    assert await Asset.filter(novel=novel).count() == original_count
    await original.refresh_from_db()
    assert original.description == "事务前描述"
    assert original.base_traits == original_traits
    assert original.source_chapters == original_source_chapters
    assert original.last_updated_chapter == 7
