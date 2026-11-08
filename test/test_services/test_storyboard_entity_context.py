import pytest

from services.storyboard.entities import visual_entity_description


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('kind', ['person', 'scene', 'item'])
def test_visual_definition_uses_current_traits_without_reference_sheet_layout(kind, language):
    traits = '齐肩黑发，灰色风衣' if language == 'zh' else 'Black shoulder-length hair, gray coat'
    prefix = {
        ("person", "zh"): "任务：完成角色的上半身正面平视特写\n角色描述：",
        ("person", "en"): "Task: Create an upper-body, front-facing, eye-level close-up\nCharacter description:",
        ("scene", "zh"): "生成四宫格画面，展示同一个场景\n场景描述：",
        ("scene", "en"): "Create a four-panel environment reference sheet\nScene description:",
        ("item", "zh"): "【道具描述】",
        ("item", "en"): "[Prop description]",
    }[(kind, language)]
    prompt = prefix + traits
    description = visual_entity_description('故事中的来访者', prompt)
    assert traits in description
    assert '故事中的来访者' in description
    assert '三视图' not in description and 'turnaround' not in description
    assert '四宫格' not in description and 'four-panel' not in description


def test_custom_traits_are_preserved_and_empty_traits_use_story_identity():
    assert visual_entity_description('来访者', '红色短发，皮夹克') == '来访者\n红色短发，皮夹克'
    assert visual_entity_description('来访者', '') == '来访者'


@pytest.mark.asyncio
async def test_generation_offers_base_and_variants_with_separate_reference_names():
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.novel import Novel
    from services.storyboard.entities import generation_entities_for_assets
    from prompts.storyboard import normalize_storyboard_reference_text, entity_reference_names

    novel = await Novel.create(name='分镜可选形态')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='苏玄',
        aliases=['小玄'], base_traits='少年布衣')
    variant = await AssetVariant.create(asset=asset, name='成年宗主', base_traits='成年金袍', chapter_numbers=[2])
    loaded = await Asset.filter(id=asset.id).prefetch_related('variants')
    entities = generation_entities_for_assets(loaded, 2, {})
    assert [entity.name for entity in entities] == ['苏玄', '苏玄#成年宗主']
    assert entities[0].description == '少年布衣'
    assert entities[1].description == '成年金袍'
    assert entities[1].variant_id == variant.id
    assert entities[1].chapter_numbers == [2]
    text = normalize_storyboard_reference_text('@{苏玄#成年宗主} 推门，少年苏玄在回忆中出现。', entities)
    assert '@{苏玄#成年宗主}' in text
    assert {entity.name for entity in entity_reference_names('@苏玄#成年宗主', entities)} == {'苏玄#成年宗主'}


def test_variant_first_appearance_does_not_reintroduce_the_same_identity():
    from schemas.scene import SceneEntity
    from prompts.asset_introductions import asset_introduction_requirement

    entities = [SceneEntity(name=name, aliases=[], description='同一主角', asset_id=1)
        for name in ('苏玄', '苏玄#成年')]
    assert asset_introduction_requirement(entities, ['苏玄'], 'zh') == ''
    assert asset_introduction_requirement(entities, ['苏玄#成年'], 'en') == ''
    assert asset_introduction_requirement(entities, [], 'zh').count('"nickname"') == 1
