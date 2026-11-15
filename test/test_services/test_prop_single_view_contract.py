"""The same single-object prop contract reaches every prompt-writing entry point."""
import json

import pytest

from prompts.creation_standards import render_asset_design
from prompts.reference import is_complete_reference_prompt
from prompts.remake_render import compact_catalog
from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('entry', ['assets', 'editing', 'image', 'remake'])
def test_all_asset_writing_entries_receive_the_single_view_prop_contract(language, entry):
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    specification = json.loads(snapshot.read('asset_contract'))[language]['item']
    rendered = instructions(snapshot, language, entry)
    assert specification['task'] in rendered
    assert specification['suffix'] in rendered
    assert specification['fields'] and all(field in rendered for field in specification['fields'])
    if language == 'zh':
        assert '普通道具默认一件物体、一个视角' in specification['task']
        assert '不自动生成三视图、四视图' in specification['task']
        assert '不能另画一件侧视物体' in specification['task']
        assert '剧情必需文字' in specification['suffix']
        assert '禁止生成任何文字' not in specification['suffix']
    else:
        assert 'one physical object and one view' in specification['task']
        assert 'Do not automatically create three-view or four-view sheets' in specification['task']
        assert 'not a second side-view object' in specification['task']
        assert 'story-essential text' in specification['suffix']
        assert 'Do not generate text' not in specification['suffix']


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_prop_rendering_preserves_inscription_and_does_not_duplicate_the_template(language):
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    spec = json.loads(snapshot.read('asset_contract'))[language]['item']
    description = '一块旧木墓牌，正面竖写“师父之墓”。' if language == 'zh' else 'One weathered wooden grave marker inscribed "Here rests the master".'
    prompt = render_asset_design(description, {}, 'item', snapshot, language, '9:16')
    assert prompt.startswith(spec['task'].format(aspect_ratio='9:16'))
    assert description in prompt
    assert prompt.endswith(spec['suffix'])
    assert is_complete_reference_prompt(prompt)
    assert render_asset_design(prompt, {}, 'item', snapshot, language, '9:16') == prompt
    catalog = compact_catalog({'objects': [{'id': 'prop-1', 'name': 'Marker', 'description': prompt}]},
                              snapshot=snapshot, language=language)
    assert catalog[0]['description'] == description


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_frozen_legacy_prop_contract_is_not_rewritten(language):
    raw = snapshot_skills()
    contracts = json.loads(raw['contents']['asset_contract'])
    old = contracts[language]['item']
    old.update(task='', fields=[], suffix='legacy prop rules')
    raw['contents']['asset_contract'] = json.dumps(contracts, ensure_ascii=False)
    snapshot = SkillSnapshot.model_validate(raw)
    existing = old['heading'] + '\nExisting approved prop design\nlegacy prop rules'
    assert is_complete_reference_prompt(existing)
    assert render_asset_design(existing, {}, 'item', snapshot, language, '16:9') == existing


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy_layout', [None, 'character_turnaround', 'group_portrait'])
async def test_existing_props_and_variants_use_single_view_without_mutating_saved_data(legacy_layout):
    from types import SimpleNamespace
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.novel import Novel
    from prompts.reference import PROP_SINGLE_VIEW
    from services.creation_agent.prompt_standards import CreationPromptStandards
    from services.creation_agent.skill_execution import current_execution

    project = await Novel.create(name='Prop protocol fixture')
    metadata = {'reference_layout': legacy_layout} if legacy_layout else {}
    prop = await Asset.create(novel=project, canonical_name='Wooden marker', asset_type=3,
                              base_traits='Existing approved prompt', metadata=metadata)
    variant = await AssetVariant.create(asset=prop, name='Weathered', base_traits='Existing variant prompt', metadata=metadata)
    standards = CreationPromptStandards(project.id)
    for target in (prop, variant):
        assert await standards.asset_kind(target) == ('item', PROP_SINGLE_VIEW)
    assert (await standards.contract('item'))['reference_layout'] == PROP_SINGLE_VIEW
    token = current_execution.set(SimpleNamespace(snapshot=SkillSnapshot.model_validate(snapshot_skills()), language='zh'))
    try:
        contract = await standards.contract('item', 'character_turnaround')
        assert contract['reference_layout'] == PROP_SINGLE_VIEW
        assert '一件物体、一个视角' in contract['asset_contract']['task']
    finally:
        current_execution.reset(token)
    await prop.refresh_from_db(); await variant.refresh_from_db()
    assert prop.metadata == variant.metadata == metadata
    assert prop.base_traits == 'Existing approved prompt'
    assert variant.base_traits == 'Existing variant prompt'


@pytest.mark.asyncio
@pytest.mark.parametrize('provided_layout', [None, 'prop_single_view'])
async def test_agent_creation_accepts_and_persists_the_prop_layout(provided_layout):
    from models.asset import Asset
    from schemas.creation_objects import CreationChangeSet
    from test.test_services.test_creation_agent_crud import crud

    service, _, _, _, _ = await crud()
    operation = {'operation': 'create_setting', 'kind': 'asset', 'client_ref': 'marker', 'asset_type': 3,
                 'name': 'Wooden marker', 'description': 'One marker', 'prompt': 'One wooden marker from the front'}
    if provided_layout:
        operation['reference_layout'] = provided_layout
    await service.apply(CreationChangeSet.model_validate({'operations': [operation]}), tool_call_id='prop-layout')
    prop = await Asset.get(canonical_name='Wooden marker')
    assert prop.metadata['reference_layout'] == 'prop_single_view'


def test_agent_tool_schemas_accept_the_layout_exposed_by_prop_rules():
    from typing import get_args, get_type_hints
    from services.creation_agent.runtime import create_creation_setting, get_creation_prompt_rules
    for tool in (create_creation_setting, get_creation_prompt_rules):
        assert 'prop_single_view' in get_args(get_type_hints(tool)['reference_layout'])
