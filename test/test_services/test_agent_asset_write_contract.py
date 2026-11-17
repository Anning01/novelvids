"""Asset writes preserve supplied designs, reject blank input and remain atomic."""
from test.agent_stream_fixtures import streaming_model
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest

from models.asset import Asset
from models.creation_agent import PromptChange
from schemas.creation_agent import AgentTarget, ImagePromptEdit
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.skill_execution import SkillExecution, current_execution
from services.creation_agent.tools import prompt_version
from test.test_services.test_asset_design_instructions import fixed_asset_prompt, synthetic_snapshot
from test.test_services.test_creation_agent_crud import crud


KINDS = [(1, 'person', 'character_turnaround'), (1, 'group', 'group_portrait'),
         (2, 'scene', 'character_turnaround'), (3, 'item', 'character_turnaround')]


@contextmanager
def workflow(snapshot=None, language='zh'):
    token = current_execution.set(SkillExecution(
        {'prompt_language': language, 'skill_snapshot': (snapshot or synthetic_snapshot()).model_dump()},
        None, AsyncMock()))
    try:
        yield
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('asset_type,kind,layout', KINDS)
async def test_agent_create_rejects_blank_and_preserves_freeform_design(asset_type, kind, layout):
    service, _, _, _, _ = await crud()
    def batch(prompt):
        return CreationChangeSet.model_validate({'operations': [{
            'operation': 'create_setting', 'client_ref': 'new', 'name': 'New design',
            'asset_type': asset_type, 'reference_layout': layout,
            'description': 'Story identity', 'prompt': prompt,
        }]})
    with workflow():
        with pytest.raises(ValueError):
            await service.apply(batch('   '), tool_call_id='invalid')
        assert not await Asset.filter(canonical_name='New design').exists()
        assert await PromptChange.all().count() == 0
        complete = 'A specific visual design without mandatory template headings.'
        result = await service.apply(batch(complete), tool_call_id='valid')
    assert (await Asset.get(id=result.changes[0]['target_id'])).base_traits == complete


@pytest.mark.asyncio
@pytest.mark.parametrize('kind_of_target', ['asset', 'variant'])
@pytest.mark.parametrize('asset_type,kind,layout', KINDS)
async def test_agent_update_and_fragment_patch_preserve_literal_content(kind_of_target, asset_type, kind, layout):
    service, _, asset, variant, _ = await crud()
    asset.asset_type = asset_type
    asset.metadata = {'reference_layout': layout}
    await asset.save()
    target = asset if kind_of_target == 'asset' else variant
    original = fixed_asset_prompt(kind=kind)
    target.base_traits = original
    await target.save()
    ref = AgentTarget(kind=kind_of_target, id=target.id)
    await service.read([ref])
    def batch(fields):
        return CreationChangeSet.model_validate({'operations': [{
            'operation': 'update_setting', 'target': ref.model_dump(), 'fields': fields,
        }]})
    with workflow():
        with pytest.raises(ValueError):
            await service.apply(batch({'prompt': '   '}), tool_call_id='blank')
        await target.refresh_from_db()
        assert target.base_traits == original
        assert await PromptChange.all().count() == 0
        heading = json.loads(synthetic_snapshot().read('asset_contract'))['zh'][kind]['heading']
        saved = await service.apply(batch({'prompt_replacements': [{'old': heading, 'new': 'My visual design'}]}), tool_call_id='valid-patch')
    assert saved.changes[0]['after']['base_traits'] == original.replace(heading, 'My visual design')



@pytest.mark.asyncio
async def test_prompt_writer_rolls_back_mixed_batch_with_a_concurrent_edit():
    from test.test_services.test_creation_agent_tools import setup_service
    service, _, asset, variant, _ = await setup_service()
    before = asset.base_traits
    edits = [ImagePromptEdit(target_kind=kind, target_id=target.id, expected_version=prompt_version(target), prompt=prompt)
             for kind, target, prompt in [('asset', asset, fixed_asset_prompt()), ('variant', variant, 'Updated variant design')]]
    edits[1].expected_version = 'stale-version'
    with workflow():
        with pytest.raises(ValueError, match='已被修改'):
            await service.update_image_prompt(edits, tool_call_id='mixed')
    await asset.refresh_from_db()
    assert asset.base_traits == before
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('asset_type,kind,layout', KINDS)
async def test_agent_rules_expose_exact_frozen_template(language, asset_type, kind, layout):
    service, _, _, _, _ = await crud()
    snapshot = synthetic_snapshot()
    with workflow(snapshot, language):
        contract = await service.prompt_standards.contract('person' if asset_type == 1 else kind, layout)
    expected = json.loads(snapshot.read('asset_contract'))[language][kind]
    assert contract['asset_contract'] == {**expected, 'task': expected['task'].format(aspect_ratio='16:9')}
    assert contract['required_fields'] == expected['fields']


@pytest.mark.asyncio
@pytest.mark.parametrize('asset_type,kind,layout', KINDS)
async def test_empty_image_prompt_is_generated_once_without_template_rewriting(asset_type, kind, layout):
    from unittest.mock import patch
    from pydantic_ai.messages import ModelResponse, TextPart
    from models.ai_task import AiTask
    from services.creation_agent.media_execution import prepare_image_prompt
    from services.creation_agent.production import conversation_for_task
    from services.creation_agent.skill_execution import prepare_workflow
    from test.test_services.test_skill_workflow import enabled_project

    novel, chapter, _ = await enabled_project()
    asset = await Asset.create(novel=novel, canonical_name='Missing prompt', asset_type=asset_type,
                               base_traits='', metadata={'reference_layout': layout})
    params = await prepare_workflow({'novel_id': novel.id, 'chapter_id': chapter.id, 'prompt_language': 'zh'})
    params['skill_snapshot'] = synthetic_snapshot().model_dump()
    task = await AiTask.create(task_type=2, status=2, request_params=params)
    message = await conversation_for_task(task)
    execution = SkillExecution({**params, 'task_id': str(task.id)}, message, AsyncMock())
    calls = 0
    complete = f'Specific {kind} design with its own visual wording.'

    def respond(messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[TextPart(json.dumps({'prompt': complete}))])

    model = streaming_model(respond)
    model.client = AsyncMock()
    token = current_execution.set(execution)
    try:
        with patch('services.creation_agent.handler.configured_model', return_value=model):
            await prepare_image_prompt(asset, None, params)
    finally:
        current_execution.reset(token)
    await asset.refresh_from_db()
    assert asset.base_traits == complete
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('contract', [None, '{}'])
async def test_frozen_legacy_or_open_source_contract_keeps_existing_writes(contract):
    service, _, asset, _, _ = await crud()
    raw = synthetic_snapshot().model_dump()
    if contract is None:
        raw['contents'].pop('asset_contract')
    else:
        raw['contents']['asset_contract'] = contract
    from prompts.skill_pack import SkillSnapshot
    with workflow(SkillSnapshot.model_validate(raw)):
        saved = await service.apply(CreationChangeSet.model_validate({'operations': [{
            'operation': 'update_setting', 'target': {'kind': 'asset', 'id': asset.id},
            'fields': {'prompt': 'A complete design in the existing public prose format.'},
        }]}), tool_call_id='compatible')
    assert saved.changes[0]['after']['base_traits'].startswith('A complete design')


@pytest.mark.asyncio
async def test_project_cover_does_not_receive_an_asset_template():
    from unittest.mock import patch
    from pydantic_ai.messages import ModelResponse, TextPart
    from models.ai_task import AiTask
    from schemas.agent_workflow import CompletePrompt
    from services.creation_agent.production import conversation_for_task
    from services.creation_agent.skill_execution import prepare_workflow
    from test.test_services.test_skill_workflow import enabled_project

    novel, chapter, _ = await enabled_project()
    params = await prepare_workflow({'novel_id': novel.id, 'chapter_id': chapter.id, 'prompt_language': 'zh'})
    params['skill_snapshot'] = synthetic_snapshot().model_dump()
    task = await AiTask.create(task_type=5, status=2, request_params=params)
    message = await conversation_for_task(task)
    execution = SkillExecution({**params, 'task_id': str(task.id)}, message, AsyncMock())
    prompt = 'Cinematic cover with a single composition and no asset reference sheet.'
    model = streaming_model(lambda messages, info: ModelResponse(parts=[TextPart(json.dumps({'prompt': prompt}))]))
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await execution.generate('image', {'cover': 'A story cover'}, CompletePrompt)
    assert result.prompt == prompt
