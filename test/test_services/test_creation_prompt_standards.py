from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from models.asset import Asset
from models.config import GeneralConfig
from models.creation_agent import PromptChange
from models.novel import Novel
from models.scene import Scene
from prompts.creation_standards import STORYBOARD_REQUIRED_SECTIONS, validate_person_visual_traits, visual_contract
from prompts.extraction import GROUP_PORTRAIT_TRAIT_LABELS, SINGLE_CHARACTER_TRAIT_LABELS, SINGLE_CHARACTER_VISUAL_RULES
from prompts.reference import GROUP_PORTRAIT, render_default_asset_prompt
from schemas.creation_agent import AgentTarget
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.runtime import CreationAgentDeps, creation_agent, get_creation_prompt_rules
from services.creation_agent.tools import PromptEditService
from test.test_services.creation_prompt_fixtures import full_scene_prompt, person_traits
from test.test_services.test_creation_agent_crud import crud


def create_setting(prompt, asset_type=1, **fields):
    return CreationChangeSet.model_validate({'operations': [{
        'operation': 'create_setting', 'client_ref': 'new', 'name': '胖子',
        'description': '主角的死党', 'asset_type': asset_type, 'prompt': prompt, **fields,
    }]})


@pytest.mark.parametrize('kind', ['person', 'scene', 'item', 'storyboard'])
@pytest.mark.parametrize('language', ['zh', 'en'])
def test_type_specific_contracts_reuse_templates_without_extraction_selection_rules(kind, language):
    result = visual_contract(kind, language=language, aspect_ratio='9:16')
    assert result == visual_contract(kind, language=language, aspect_ratio='9:16')
    assert result['kind'] == kind and result['language'] == language
    assert '{prompt_language_name}' not in str(result)
    assert '至少出现两次' not in result['writing_rules']
    assert '至少出现2次' not in result['writing_rules']
    if kind == 'person':
        assert result['required_fields'] == list(SINGLE_CHARACTER_TRAIT_LABELS)
        assert '9:16' in result['rendering']
    else:
        assert SINGLE_CHARACTER_VISUAL_RULES not in result['writing_rules']


@pytest.mark.parametrize('bad', [
    '胖胖的，短发，戴眼镜',
    person_traits(发型=''), person_traits(发型='未知'),
    person_traits() + '\n发型: long hair',
])
@pytest.mark.asyncio
async def test_invalid_character_cannot_be_persisted_or_emit_success(bad):
    service, _, _, _, _ = await crud()
    with pytest.raises(ValueError, match='字段|占位'):
        await service.apply(create_setting(bad), tool_call_id='invalid')
    assert not await Asset.filter(canonical_name='胖子').exists()
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('asset_type,text', [(1, person_traits()), (2, '庭院中央是石井，东侧木门，青砖围墙，阴天柔光。'),
                                          (3, '圆形铜表，白色表盘，黑色指针，表壳边缘磨损。')])
async def test_creation_persists_same_reference_template_as_normal_generation(asset_type, text):
    service, _, _, _, _ = await crud()
    await GeneralConfig.create(prompt_language='zh')
    await Novel.filter(id=service.novel_id).update(aspect_ratio='9:16')
    saved = await service.apply(create_setting(text, asset_type), tool_call_id='create')
    target = await Asset.get(id=saved.changes[0]['target_id'])
    expected = render_default_asset_prompt(asset_type={1: 'person', 2: 'scene', 3: 'item'}[asset_type],
        visual_traits=text, prompt_language='zh', aspect_ratio='9:16')
    assert target.base_traits == expected
    await service.read([AgentTarget(kind='asset', id=target.id)])
    await service.apply(CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
        'target': {'kind': 'asset', 'id': target.id}, 'fields': {'prompt': expected}}]}), tool_call_id='same')
    await target.refresh_from_db()
    assert target.base_traits == expected


@pytest.mark.asyncio
async def test_group_contract_and_metadata_survive_creation_and_reading():
    service, _, _, _, _ = await crud()
    text = '\n'.join(f'{label}: 明确的群像特征' for label in GROUP_PORTRAIT_TRAIT_LABELS)
    saved = await service.apply(create_setting(text, reference_layout=GROUP_PORTRAIT), tool_call_id='group')
    target = await Asset.get(id=saved.changes[0]['target_id'])
    assert await service.prompt_standards.asset_kind(target) == ('person', GROUP_PORTRAIT)
    assert target.base_traits == text  # Existing group policy has no turnaround wrapper.
    assert (await service.prompt_standards.contract('person', GROUP_PORTRAIT))['required_fields'] == list(GROUP_PORTRAIT_TRAIT_LABELS)


@pytest.mark.asyncio
async def test_character_patch_preserves_other_traits_template_and_undo():
    service, _, _, _, _ = await crud()
    saved = await service.apply(create_setting(person_traits()), tool_call_id='create')
    target = await Asset.get(id=saved.changes[0]['target_id'])
    original = target.base_traits
    ref = AgentTarget(kind='asset', id=target.id)
    await service.read([ref])
    patched = await service.apply(CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
        'target': ref.model_dump(), 'fields': {'prompt_replacements': [
            {'old': 'short black hair', 'new': 'short black hair with a side part'},
        ]}}]}), tool_call_id='patch')
    await target.refresh_from_db()
    assert target.base_traits == original.replace('short black hair', 'short black hair with a side part')
    validate_person_visual_traits(target.base_traits)
    await service.undo(patched.id)
    await target.refresh_from_db()
    assert target.base_traits == original
    await service.read([ref])
    with pytest.raises(ValueError, match='14项'):
        await service.apply(CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
            'target': ref.model_dump(), 'fields': {'prompt': '胖胖的短发男生'}}]}), tool_call_id='degrade')


@pytest.mark.asyncio
async def test_legacy_exact_patch_remains_local_but_full_rewrite_requires_contract():
    service, _, asset, _, _ = await crud()
    saved = await service.apply(CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
        'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'prompt_replacements': [
            {'old': '灰色', 'new': '深灰色'}]}}]}), tool_call_id='local')
    await asset.refresh_from_db()
    assert asset.base_traits == '深灰色风衣'
    await service.undo(saved.id)
    await asset.refresh_from_db()
    assert asset.base_traits == '灰色风衣'


@pytest.mark.asyncio
async def test_new_raw_storyboard_requires_complete_sections_and_edit_cannot_drop_them():
    service, scene, _, _, _ = await crud()
    def new_scene(text):
        return CreationChangeSet.model_validate({'operations': [{'operation': 'create_scene', 'client_ref': 'new',
            'description': '庭院空镜', 'duration': 3, 'prompt': text}]})
    with pytest.raises(ValueError, match='必要栏目'):
        await service.apply(new_scene('一座安静的庭院'), tool_call_id='incomplete')
    with pytest.raises(ValueError, match='不能为空'):
        await service.apply(new_scene('\n'.join(f'【{name}】' for name in STORYBOARD_REQUIRED_SECTIONS)), tool_call_id='empty')
    assert await Scene.all().count() == 1
    saved = await service.apply(new_scene(full_scene_prompt('庭院中央的井台位于画面中央，固定机位。')), tool_call_id='complete')
    target_id = saved.changes[0]['target_id']
    await service.read([AgentTarget(kind='scene', id=target_id)])
    with pytest.raises(ValueError, match='必要栏目'):
        await service.apply(CreationChangeSet.model_validate({'operations': [{'operation': 'update_scene',
            'scene_id': target_id, 'fields': {'prompt': '改成暖光'}}]}), tool_call_id='degrade')
    assert await Scene.filter(id=scene.id).exists()


@pytest.mark.asyncio
async def test_rules_tool_uses_actual_type_and_project_language_and_rejects_other_project():
    service, _, asset, _, _ = await crud()
    await GeneralConfig.create(prompt_language='zh')
    await Novel.filter(id=service.novel_id).update(style_key='realistic-general')
    ctx = SimpleNamespace(deps=CreationAgentDeps(service=None, changes=service, context={}),
                          model=None, tool_call_id='rules')
    rules = await get_creation_prompt_rules(ctx, 'item', target=AgentTarget(kind='asset', id=asset.id))
    assert rules['prompt_rules']['kind'] == 'person' and rules['prompt_rules']['language'] == 'zh'
    assert '摄影质感' in rules['prompt_rules']['project_style']
    assert rules['targets'][0]['id'] == asset.id
    other = await Novel.create(name='另一个项目')
    foreign = await Asset.create(novel=other, canonical_name='外部人物', asset_type=1, base_traits='不应读取的内容')
    with pytest.raises(ModelRetry, match='不存在'):
        await get_creation_prompt_rules(ctx, 'person', target=AgentTarget(kind='asset', id=foreign.id))


@pytest.mark.asyncio
async def test_reference_template_cannot_be_applied_to_wrong_type():
    service, _, _, _, _ = await crud()
    wrong = render_default_asset_prompt(asset_type='scene', visual_traits='青砖庭院')
    with pytest.raises(ValueError, match='类型不符'):
        await service.apply(create_setting(wrong, asset_type=3), tool_call_id='wrong-kind')
    assert not await Asset.filter(canonical_name='胖子').exists()


@pytest.mark.asyncio
async def test_full_traits_edit_preserves_custom_character_composition():
    service, _, asset, _, _ = await crud()
    custom = '任务：完成角色的上半身正面平视特写，保留自定义构图。\n\n角色描述：\n' + person_traits()
    await Asset.filter(id=asset.id).update(base_traits=custom)
    ref = AgentTarget(kind='asset', id=asset.id)
    await service.read([ref])
    updated = person_traits(发型='short black hair, side part')
    await service.apply(CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
        'target': ref.model_dump(), 'fields': {'prompt': updated}}]}), tool_call_id='traits-only')
    await asset.refresh_from_db()
    assert asset.base_traits == custom.replace(person_traits(), updated)


@pytest.mark.asyncio
async def test_agent_loads_one_contract_then_creates_complete_prompt_in_three_calls():
    service, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=service.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert 'get_creation_prompt_rules' in {tool.name for tool in info.function_tools}
            assert '14行' not in info.instructions  # Heavy rules are on demand.
            return ModelResponse(parts=[ToolCallPart('get_creation_prompt_rules', {'kind': 'person'}, tool_call_id='rules')])
        result = [part.content for message in messages for part in message.parts if isinstance(part, ToolReturnPart)][-1]
        if calls == 2:
            assert result['prompt_rules']['required_fields'] == list(SINGLE_CHARACTER_TRAIT_LABELS)
            return ModelResponse(parts=[ToolCallPart('create_creation_setting', {
                'name': '胖子', 'asset_type': 1, 'description': '主角的死党',
                'prompt': person_traits(脸型='round face, dark eyes, round glasses', 身材='stocky build'),
            }, tool_call_id='create')])
        assert result['status'] == 'saved'
        return ModelResponse(parts=[TextPart('已创建胖子，补齐人物形象。')])
    await creation_agent.run('帮我创建胖子，主角的死党，胖胖的短发戴眼镜', model=FunctionModel(respond),
        deps=CreationAgentDeps(service=legacy, changes=service, context={}), usage_limits=UsageLimits(request_limit=4))
    target = await Asset.get(novel_id=service.novel_id, canonical_name='胖子')
    assert calls == 3 and 'round glasses' in target.base_traits and 'three-view' in target.base_traits
