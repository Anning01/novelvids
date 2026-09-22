import pytest

from prompts.reference import render_default_asset_prompt
from services.storyboard.entities import visual_entity_description


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('kind', ['person', 'scene', 'item'])
def test_visual_definition_uses_current_traits_without_reference_sheet_layout(kind, language):
    traits = '齐肩黑发，灰色风衣' if language == 'zh' else 'Black shoulder-length hair, gray coat'
    prompt = render_default_asset_prompt(asset_type=kind, visual_traits=traits, prompt_language=language)
    description = visual_entity_description('故事中的来访者', prompt)
    assert traits in description
    assert '故事中的来访者' in description
    assert '三视图' not in description and 'turnaround' not in description
    assert '四宫格' not in description and 'four-panel' not in description


def test_custom_traits_are_preserved_and_empty_traits_use_story_identity():
    assert visual_entity_description('来访者', '红色短发，皮夹克') == '来访者\n红色短发，皮夹克'
    assert visual_entity_description('来访者', '') == '来访者'
