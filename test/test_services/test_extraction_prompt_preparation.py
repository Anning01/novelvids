from services.extraction.extractor import (
    AssetExtractionResult,
    Item,
    Person,
    Scene,
)
import pytest
from models.asset import Asset
from models.novel import Novel
from services.extraction.persistence import AssetUpsertService


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


@pytest.mark.asyncio
async def test_extracted_complete_prompts_are_persisted_without_hidden_templates():
    result = AssetExtractionResult(
        persons=[
            Person(
                name="张三",
                base_traits=PERSON_TRAITS,
            )
        ],
        scenes=[
            Scene(
                name="旧宅",
                base_traits="青灰砖墙，木门，夜间冷光",
            )
        ],
        items=[
            Item(
                name="铜表",
                base_traits="银色表壳，白色表盘，黑色指针",
            )
        ],
    )

    novel = await Novel.create(name="Story")
    await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=1, result=result)

    assert result.persons[0].base_traits == PERSON_TRAITS
    assert (await Asset.get(novel_id=novel.id, canonical_name="张三")).base_traits == PERSON_TRAITS
    assert (await Asset.get(novel_id=novel.id, canonical_name="旧宅")).base_traits == "青灰砖墙，木门，夜间冷光"
    assert (await Asset.get(novel_id=novel.id, canonical_name="铜表")).base_traits == "银色表壳，白色表盘，黑色指针"


@pytest.mark.asyncio
async def test_historical_complete_user_prompt_is_not_wrapped_twice():
    complete_prompt = (
        "任务：完成角色的上半身正面平视特写和该角色的全身三视图，"
        "这是已经保存的完整自定义 Prompt。"
    )
    result = AssetExtractionResult(
        persons=[Person(name="张三", base_traits=PERSON_TRAITS)],
        scenes=[Scene(name="旧宅", base_traits=complete_prompt)],
        items=[],
    )

    novel = await Novel.create(name="Story")
    await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=1, result=result)

    assert (await Asset.get(novel_id=novel.id, canonical_name="旧宅")).base_traits == complete_prompt
