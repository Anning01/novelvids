import json
import re

import pytest
from pydantic import ValidationError

from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills
from schemas.agent_workflow import RemakeShot
from services.remake.storyboards import prepare_remake_prompt
from services.remake.asset_validation import render_remake_assets
from prompts.remake_render import compact_catalog
from test.remake_fixtures import design_fields, remake_shot, synthetic_snapshot


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_remake_phases_receive_their_own_complete_protocol(language):
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    assets = instructions(snapshot, language, 'remake', output_kind='global_key_assets')
    shots = instructions(snapshot, language, 'remake', output_kind='professional_video_prompt_material')
    assert snapshot.read('image') in assets
    assert snapshot.read('assets') in assets
    for contract in json.loads(snapshot.read('asset_contract')).get(language, {}).values():
        assert contract['heading'] in assets
    assert snapshot.read('storyboard') in shots
    assert snapshot.read('image') not in shots
    assert '核心生成指令' in shots or 'Primary generation instruction' in shots


def test_remake_cannot_return_an_unstructured_prompt_in_place_of_storyboard_fields():
    with pytest.raises(ValidationError):
        RemakeShot.model_validate({'prompt': 'A brief visual summary.', 'asset_refs': [], 'confidence': .9})


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('kind,count', [('person',14),('group',15)])
def test_asset_renderer_uses_configured_template_field_order_and_ratio(language, kind, count):
    snapshot = synthetic_snapshot()
    raw = {'characters': [{'name':'将军','description':'Visual evidence', 'label':'群像' if kind=='group' else '人物',
        'visual_fields':dict(reversed(list(design_fields(kind, language=language).items())))}],
        'scenes':[{'name':'军帐','description':'A tent with clear spatial relationships','visual_fields':{}}],
        'objects':[{'name':'令牌','description':'A dark wooden token with a carved edge','visual_fields':{}}]}
    result = render_remake_assets(raw, snapshot, language, '9:16')
    person = result['characters'][0]['description']
    assert person.startswith(f'Task:{language}:{kind}:9:16')
    assert len(re.findall(r'^\*\*.+?\*\*：', person, re.M)) == count
    assert result['objects'][0]['description'].endswith('END-GUARD')
    compact = compact_catalog(result, snapshot=snapshot, language=language)
    assert all('Task:' not in item['description'] and 'END-GUARD' not in item['description'] for item in compact)


@pytest.mark.parametrize('duration', [4, 4.266667])
def test_remake_uses_shared_eight_section_renderer_without_timing_precision_loss(duration):
    from prompts.labels import prompt_label
    snapshot = synthetic_snapshot()
    catalog=[{'id':'character-001','name':'将军','type':'character','description':'黑甲'}]
    for language in ('zh','en'):
        result = prepare_remake_prompt(remake_shot(duration=duration), catalog, snapshot, language,
                                      duration_seconds=duration)
        position = 0
        for heading in json.loads(snapshot.read('storyboard_contract'))['sections']:
            position = result['prompt'].index(prompt_label(heading, language), position) + len(prompt_label(heading, language))
        assert result['duration_seconds'] == duration
        assert '@{将军}' in result['prompt']


def test_unknown_asset_reference_cannot_reach_persistence():
    with pytest.raises(ValueError, match='未登记资产'):
        prepare_remake_prompt(remake_shot(refs=[{'asset_id':'unknown','asset_name':'虚构','asset_type':'character'}]),
            [], synthetic_snapshot(), 'zh')


def test_source_duration_controls_rounded_model_timeline_without_losing_content():
    raw = remake_shot(duration=4.27)
    raw['shot_index'] = 3
    raw['sequence'] = 1
    result = prepare_remake_prompt(raw, [{'id':'character-001','name':'将军','type':'character','description':'黑甲'}],
        synthetic_snapshot(), 'zh', duration_seconds=4.266667)
    assert result['duration_seconds'] == 4.266667 and result['sequence'] == 3
    assert '4.26667s' in result['actions'][0]
    assert '抬眼' in result['actions'][0]
    raw['actions'] = ['0s-8s: @将军抬眼。']
    with pytest.raises(ValueError, match='超出镜头时长'):
        prepare_remake_prompt(raw, [{'id':'character-001','name':'将军','type':'character','description':'黑甲'}],
            synthetic_snapshot(), 'zh', duration_seconds=4.266667)


def test_explicit_scene_reference_is_preserved_even_when_prose_uses_a_shorter_name():
    raw = remake_shot(refs=[])
    raw['asset_refs'] = [{'asset_id':'scene-001','asset_name':'实验室','asset_type':'scene'}]
    result = prepare_remake_prompt(raw, [{'id':'scene-001','name':'未来医疗舱/实验室','type':'scene','description':'冷色空间'}],
        synthetic_snapshot(), 'zh', duration_seconds=4.2)
    assert '场景参考：@{未来医疗舱/实验室}' in result['prompt']
    assert result['asset_refs'] == [{'asset_id':'scene-001','asset_name':'未来医疗舱/实验室','asset_type':'scene'}]


def test_validation_errors_remain_serializable_in_model_audit_history():
    from pydantic_ai.messages import ModelRequest, RetryPromptPart
    from services.creation_agent.skill_execution import _audit_messages
    request = ModelRequest(parts=[RetryPromptPart(content=[{
        'type':'value_error','loc':('duration',),'msg':'Invalid duration','input':'4s',
        'ctx':{'error':ValueError('Segment durations must match')},
    }])])
    messages = _audit_messages([request])
    assert messages[0]['parts'][0]['content'][0]['ctx']['error'] == 'Segment durations must match'
