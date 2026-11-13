import pytest
import json

from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills
from services.extraction.extractor import AssetExtractionResult
from test.visual_fields import trait_labels



def synthetic_asset_contract():
    # Synthetic templates isolate contract validation from editorial changes.
    return {language: {kind: {
        "task": f"Task:{language}:{kind}:{{aspect_ratio}}" if kind != "item" else "",
        "heading": "角色描述：" if kind == "person" else f"Description:{kind}:",
        "fields": list(trait_labels(group=kind == "group", language=language)) if kind in ("person", "group") else [],
        "suffix": "END-GUARD" if kind == "item" else "",
    } for kind in ("person", "group", "scene", "item")} for language in ("zh", "en")}


def synthetic_snapshot():
    raw = snapshot_skills()
    raw["contents"]["asset_contract"] = json.dumps(synthetic_asset_contract())
    return SkillSnapshot.model_validate(raw)


def fixed_asset_prompt(language="zh", kind="person", ratio="16:9", snapshot=None):
    snapshot = snapshot or synthetic_snapshot()
    contract = json.loads(snapshot.read("asset_contract"))[language][kind]
    if kind == "person":
        values = ["Modern city", "China", "Chinese", "Realistic drama", "Oval face, straight brows, dark eyes, rounded nose, thin lips",
                  "Short straight black hair", "No earrings", "Lean, medium height", "Seven heads tall",
                  "Navy cotton school jacket", "Navy straight trousers", "White canvas shoes", "Male", "18 years old"]
    elif kind == "group":
        values = ["School students", "17 to 18", "Mixed genders", "Chinese", "Five students", "Naturally varied heights",
                  "Oval and square faces", "Straight dark brows", "No glasses", "Naturally varied noses", "Natural lip colors",
                  "Natural skin texture", "No distinctive marks", "Short and tied black hair", "Navy cotton school uniforms"]
    else:
        values = []
    details = '\n'.join(f"**{field}**: {value}" for field, value in zip(contract['fields'], values)) if values else 'A concrete, stable visual design with clear spatial or structural relationships.'
    parts = [contract['task'].format(aspect_ratio=ratio), contract['heading'], details, contract.get('suffix', '')]
    return '\n\n'.join(part for part in parts if part)


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_fixed_fields_match_the_original_14_and_15_field_contracts(language):
    snapshot = synthetic_snapshot()
    specification = json.loads(snapshot.read('asset_contract'))[language]
    assert specification['person']['fields'] == list(trait_labels(language=language))
    assert specification['group']['fields'] == list(trait_labels(group=True, language=language))
    assert '资产输出协议' in instructions(snapshot, language, 'assets')


@pytest.mark.parametrize('language,design', [
    ('zh', '次卧的正面用暖橙色晨光，反向机位用窗外透入的冷蓝色月光。'),
    ('en', 'The front view uses amber morning light. The reverse view uses cool blue moonlight.'),
])
def test_asset_candidates_preserve_model_wording_and_scene_colors(language, design):
    from services.extraction.validation import AssetCandidateValidator

    snapshot = synthetic_snapshot()
    validator = AssetCandidateValidator(AssetExtractionResult)
    draft = validator.draft_type.model_validate({
        'persons': [], 'items': [],
        'scenes': [{'name': '次卧', 'base_traits': design, 'variant': {
            'name': '夜间', 'base_traits': design, 'change_reason': '切换时段',
        }}],
    })
    accepted = validator.merge(draft)
    assert not validator.issues
    assert accepted.scenes[0].base_traits == accepted.scenes[0].variant.base_traits == design
    assert '资产输出协议' in instructions(snapshot, language, 'assets')


@pytest.mark.parametrize("language", ["zh", "en"])
def test_asset_extraction_includes_image_contract_without_tool_reads(language):
    raw = snapshot_skills()
    raw["contents"]["image"] = "Frozen image rules for this run"
    snapshot = SkillSnapshot.model_validate(raw)
    rendered = instructions(snapshot, language, "assets")
    assert snapshot.read("image") in rendered
    assert snapshot.read("assets") in rendered
    assert f"language={language}" in rendered
    assert "Frozen image rules" not in instructions(snapshot, language, "story")


def test_asset_design_rules_cover_specific_designs_instead_of_plot_summaries():
    rules = SkillSnapshot.model_validate(snapshot_skills()).read("assets")
    for requirement in (
        "眉眼", "鼻梁", "嘴唇", "头身比", "上装", "下装", "鞋履",
        "人数规模", "个体差异", "近景、中景、远景", "空间拓扑",
        "结构部件", "磨损", "普通校服", "具体的视觉设计",
    ):
        assert requirement in rules


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('skill', ['assets', 'editing', 'image'])
def test_all_asset_writers_receive_layout_guidance_and_allow_user_design_choices(language, skill):
    snapshot = synthetic_snapshot()
    rendered = instructions(snapshot, language, skill)
    contract = json.loads(snapshot.read('asset_contract'))[language]
    for kind in ('person', 'group', 'scene', 'item'):
        assert contract[kind]['heading'] in rendered
        assert contract[kind]['task'] in rendered
    assert '按用户意图和资产类型组织具体视觉内容' in rendered
    assert '项目封面按封面任务生成' in rendered


def test_creative_requirements_preserve_user_text_inside_mandatory_format():
    from prompts.skill_pack import creative_requirements
    text = '把主角弄帅一些，特别一些'
    for language in ('zh', 'en'):
        result = creative_requirements(text, language)
        assert result.endswith(text)
        assert '格式' in result if language == 'zh' else 'format' in result
    from prompts.skill_pack import read_skill
    editing = read_skill('editing')
    assert '不要求固定自然语言栏位' not in editing


@pytest.mark.parametrize(('language', 'empty_scene'), [('zh', '空场景'), ('en', 'unoccupied')])
def test_scene_renderer_adds_layout_and_ratio_without_overriding_the_color_design(language, empty_scene):
    from prompts.creation_standards import render_asset_design

    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    contract = json.loads(snapshot.read('asset_contract'))[language]['scene']
    design = '暖光正面，冷光反面。' if language == 'zh' else 'Warm front view, cool reverse view.'
    result = render_asset_design(design, {}, 'scene', snapshot, language, '9:16')
    assert result.startswith(contract['task'].format(aspect_ratio='9:16'))
    assert design in result
    assert result.endswith(contract['suffix']) and empty_scene in result
    assert '光照一致' not in result and 'lighting consistent' not in result
    for skill in ('image', 'assets', 'remake'):
        assert contract['suffix'] in instructions(snapshot, language, skill)
