import pytest
import json

from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills
from services.extraction.extractor import AssetExtractionResult, Person, Scene, Item, validate_asset_prompt_contract
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


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('kind', ['person', 'group', 'animal', 'scene', 'item'])
def test_new_asset_prompts_require_full_tasks_and_type_specific_descriptions(language, kind):
    actual_kind = 'person' if kind == 'animal' else kind
    prompt = fixed_asset_prompt(language, actual_kind, '9:16')
    if kind in ('person', 'group', 'animal'):
        result = AssetExtractionResult(persons=[Person(name='Test', label={'person':'人物','group':'群像','animal':'动物'}[kind], base_traits=prompt)], scenes=[], items=[])
    elif kind == 'scene':
        result = AssetExtractionResult(persons=[], scenes=[Scene(name='Test', base_traits=prompt)], items=[])
    else:
        result = AssetExtractionResult(persons=[], scenes=[], items=[Item(name='Test', base_traits=prompt)])
    snapshot = synthetic_snapshot()
    validate_asset_prompt_contract(result, snapshot, language, '9:16')
    if kind != 'item':  # The original prop template has no aspect-ratio placeholder.
        with pytest.raises(ValueError, match='complete task template'):
            validate_asset_prompt_contract(result, snapshot, language, '16:9')


def test_optional_template_requires_both_heading_and_final_guard():
    snapshot = synthetic_snapshot()
    prompt = fixed_asset_prompt(kind='item')
    for invalid in (prompt.replace('Description:item:', ''), prompt.rsplit('\n\n', 1)[0], 'Description:item:\nEND-GUARD'):
        result = AssetExtractionResult(persons=[], scenes=[], items=[Item(name='Test', base_traits=invalid)])
        with pytest.raises(ValueError):
            validate_asset_prompt_contract(result, snapshot, 'zh', '16:9')


def test_historical_empty_contract_keeps_existing_free_text_behavior():
    raw = snapshot_skills()
    raw['contents']['asset_contract'] = '{}'
    snapshot = SkillSnapshot.model_validate(raw)
    result = AssetExtractionResult(persons=[Person(name='Public', base_traits='Existing public free-text design')], scenes=[], items=[])
    validate_asset_prompt_contract(result, snapshot, 'zh', '16:9')
    assert '\n资产输出协议：\n' not in instructions(snapshot, 'zh', 'assets')


@pytest.mark.parametrize('change', ['no_task', 'prose', 'missing_field', 'wrong_order', 'placeholder'])
def test_shortened_or_unstructured_designs_are_rejected_before_persistence(change):
    snapshot = synthetic_snapshot()
    prompt = fixed_asset_prompt()
    if change == 'no_task':
        prompt = prompt.split('角色描述：', 1)[1]
    elif change == 'prose':
        prompt = prompt.split('角色描述：', 1)[0] + '角色描述：\n十八岁男生，普通校服。'
    elif change == 'missing_field':
        prompt = prompt.replace('**性别**: Male\n', '')
    elif change == 'wrong_order':
        prompt = prompt.replace('**性别**: Male\n**年龄**: 18 years old', '**年龄**: 18 years old\n**性别**: Male')
    else:
        prompt = prompt.replace('**性别**: Male', '**性别**: 未提及')
    result = AssetExtractionResult(persons=[Person(name='Test', base_traits=prompt)], scenes=[], items=[])
    with pytest.raises(ValueError):
        validate_asset_prompt_contract(result, snapshot, 'zh', '16:9')


def test_historical_queued_snapshots_do_not_receive_new_contracts():
    raw = snapshot_skills()
    del raw['contents']['asset_contract']
    snapshot = SkillSnapshot.model_validate(raw)
    result = AssetExtractionResult(persons=[Person(name='Old', base_traits='Historical prompt')], scenes=[], items=[])
    validate_asset_prompt_contract(result, snapshot, 'zh', '16:9')


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
        "结构部件", "磨损", "普通校服", "逐项自检",
    ):
        assert requirement in rules


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('skill', ['assets', 'editing', 'image'])
def test_all_asset_writers_receive_mandatory_format_above_user_preferences(language, skill):
    snapshot = synthetic_snapshot()
    rendered = instructions(snapshot, language, skill)
    contract = json.loads(snapshot.read('asset_contract'))[language]
    for kind in ('person', 'group', 'scene', 'item'):
        assert contract[kind]['heading'] in rendered
        assert contract[kind]['task'] in rendered
    assert '用户补充要求只用于协议允许的设计内容' in rendered
    assert '项目封面不适用资产协议' in rendered


def test_creative_requirements_preserve_user_text_inside_mandatory_format():
    from prompts.skill_pack import creative_requirements
    text = '把主角弄帅一些，特别一些'
    for language in ('zh', 'en'):
        result = creative_requirements(text, language)
        assert result.endswith(text)
        assert '格式' in result if language == 'zh' else 'format' in result
    from pathlib import Path
    editing = (Path(__file__).parents[2] / 'prompts/skills/editing.md').read_text()
    assert '不要求固定自然语言栏位' not in editing
