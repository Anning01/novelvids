from services.extraction.extractor import (
    AssetExtractionResult,
    Item,
    Person,
    Scene,
)
from services.extraction.prompt_preparation import AssetPromptPreparationService


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


def test_preparation_persists_complete_default_prompts_without_mutating_traits():
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

    prepared = AssetPromptPreparationService().prepare(
        result,
        prompt_language="zh",
    )

    assert result.persons[0].base_traits == PERSON_TRAITS
    assert prepared.persons[0].base_traits.startswith(
        "任务：完成角色的上半身正面平视特写"
    )
    assert "正面全身、侧面全身、背面全身" in prepared.persons[0].base_traits
    assert PERSON_TRAITS in prepared.persons[0].base_traits
    assert prepared.scenes[0].base_traits.startswith(
        "生成四宫格画面，展示同一个场景中的四个不同视角"
    )
    assert prepared.items[0].base_traits.startswith(
        "【道具描述】银色表壳，白色表盘，黑色指针"
    )


def test_preparation_does_not_wrap_an_already_complete_user_prompt_twice():
    complete_prompt = (
        "任务：完成角色的上半身正面平视特写和该角色的全身三视图，"
        "这是已经保存的完整自定义 Prompt。"
    )
    result = AssetExtractionResult(
        persons=[Person(name="张三", base_traits=PERSON_TRAITS)],
        scenes=[Scene(name="旧宅", base_traits=complete_prompt)],
        items=[],
    )

    prepared = AssetPromptPreparationService().prepare(
        result,
        prompt_language="zh",
    )

    assert prepared.scenes[0].base_traits == complete_prompt
