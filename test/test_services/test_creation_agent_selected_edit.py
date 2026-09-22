import json

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.usage import UsageLimits

from models.asset import Asset
from models.scene import Scene
from prompts.storyboard import format_storyboard_prompt
from schemas.creation_agent import AgentTarget
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.changes import CreationChanges
from services.creation_agent.runtime import CreationAgentDeps, stream_creation_agent
from services.creation_agent.tools import PromptEditService
from test.test_services.test_creation_agent_crud import crud
from test.test_services.test_storyboard_handler import _shot


async def reference_fixture(structured=False):
    service, scene, person, variant, task = await crud()
    variant.base_traits = person.base_traits
    await variant.save()
    prop = await Asset.create(novel_id=service.novel_id, canonical_name='铜表', asset_type=3,
                             base_traits='白色表盘，黑色指针', source_chapters=[1])
    await scene.assets.add(person, prop)
    entities = await PromptEditService._entities(scene)
    shot = _shot(scene.sequence, '@{女主}低头查看@{铜表}。').model_copy(update={
        'duration': '6s', 'actions': ['0s-6s: @{女主}低头查看@{铜表}。'],
        'dialogue': ['0s-2s: @{女主}（平静）：该出发了。'],
    })
    scene.description = shot.description
    scene.prompt = format_storyboard_prompt(shot, entities=entities)
    scene.prompt_params = shot.model_dump(exclude={'sequence', 'duration', 'description'}) if structured else {
        'dialogue': shot.dialogue, 'sound_design': shot.sound_design,
    }
    await scene.save()
    sibling = await Scene.create(chapter_id=scene.chapter_id, sequence=6, prompt=scene.prompt,
                                 prompt_params=scene.prompt_params, duration=6)
    ref = AgentTarget(kind='scene', id=scene.id)
    service = CreationChanges(novel_id=service.novel_id, task_id=task.id, max_batch_size=8,
        request=service.request.model_copy(update={'write_scope': 'selected', 'targets': [ref]}))
    await service.read([ref])
    return service, scene, person, prop, sibling, task


def reference_change(scene_id, types):
    return CreationChangeSet.model_validate({'operations': [{'operation': 'update_scene', 'scene_id': scene_id,
        'fields': {'visual': {'reference_only_types': types}}}]})


@pytest.mark.asyncio
@pytest.mark.parametrize('structured', [False, True])
async def test_reference_only_edit_preserves_binding_action_audio_other_types_and_undo(structured):
    service, scene, person, prop, sibling, _ = await reference_fixture(structured)
    original, original_params = scene.prompt, scene.prompt_params
    assert '角色设定图' in original and person.base_traits in original
    saved = await service.apply(reference_change(scene.id, ['人物']), tool_call_id='reference-only')
    await scene.refresh_from_db()
    assert '角色设定图' not in scene.prompt and person.base_traits not in scene.prompt
    assert '角色参考：@{女主}' in scene.prompt
    assert prop.base_traits in scene.prompt
    assert '0s-6s: @{女主}低头查看@{铜表}。' in scene.prompt
    assert scene.prompt_params['dialogue'] == original_params['dialogue']
    assert scene.prompt_params['reference_only_types'] == ['人物']
    assert set(await scene.assets.all().values_list('id', flat=True)) == {person.id, prop.id}
    assert (await Scene.get(id=sibling.id)).prompt == original
    read = (await service.read([AgentTarget(kind='scene', id=scene.id)]))[0]
    assert read['reference_only_types'] == ['人物']
    await service.undo(saved.id)
    await scene.refresh_from_db()
    assert scene.prompt == original and scene.prompt_params == original_params


@pytest.mark.asyncio
async def test_legacy_reference_mode_survives_later_prompt_edit_and_can_restore_definitions():
    service, scene, person, _, _, _ = await reference_fixture()
    await service.apply(reference_change(scene.id, ['人物']), tool_call_id='reference-only')
    await scene.refresh_from_db()
    await service.read([AgentTarget(kind='scene', id=scene.id)])
    await service.apply(CreationChangeSet.model_validate({'operations': [{'operation': 'update_scene', 'scene_id': scene.id,
        'fields': {'prompt': scene.prompt.replace('该出发了', '我们出发吧')}}]}), tool_call_id='later-edit')
    await scene.refresh_from_db()
    assert person.base_traits not in scene.prompt and '我们出发吧' in scene.prompt
    assert scene.prompt_params['reference_only_types'] == ['人物']
    await service.read([AgentTarget(kind='scene', id=scene.id)])
    await service.apply(reference_change(scene.id, []), tool_call_id='restore')
    await scene.refresh_from_db()
    assert person.base_traits in scene.prompt


@pytest.mark.asyncio
async def test_streamed_followup_uses_current_selection_not_old_project_wide_request():
    service, scene, person, _, sibling, task = await reference_fixture()
    legacy = PromptEditService(novel_id=service.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            current = [part for message in messages for part in message.parts if isinstance(part, UserPromptPart)][-1]
            request = json.loads(current.content)
            assert request['user_request'] == '帮我改啊'
            assert request['current_selection'] == {'chapter_id': scene.chapter_id, 'write_scope': 'selected',
                'selected_targets': [{'kind': 'scene', 'id': scene.id}]}
            reader = next(tool for tool in info.function_tools if tool.name == 'read_creation_objects')
            assert reader.parameters_json_schema['properties']['targets']['maxItems'] == 8
            yield {0: DeltaToolCall(name='get_creation_context', json_args=json.dumps({'capabilities': ['update_scene']}), tool_call_id='context')}
        elif calls == 2:
            context = [p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart)][-1]
            assert [target['id'] for target in context['targets']] == [scene.id]
            assert context['catalog'] is None
            yield {0: DeltaToolCall(name='apply_creation_changes', json_args=reference_change(scene.id, ['人物']).model_dump_json(exclude_unset=True), tool_call_id='write')}
        else:
            receipt = [p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart)][-1]
            assert receipt['status'] == 'saved'
            yield '已调整当前分镜，只保留人物引用。'

    history = [ModelRequest(parts=[UserPromptPart('以后整章人物都通过引用，不要展开外貌。')]),
               ModelResponse(parts=[TextPart('已记住这个要求。')])]
    events = [event async for event in stream_creation_agent(message='帮我改啊', conversation_id='1', run_id=str(task.id),
        model=FunctionModel(stream_function=model), deps=CreationAgentDeps(service=legacy, changes=service, context={}),
        message_history=history, usage_limits=UsageLimits(request_limit=4))]
    assert not any(event.type == 'RUN_ERROR' for event in events), [event for event in events if event.type == 'RUN_ERROR']
    await scene.refresh_from_db()
    assert calls == 3 and person.base_traits not in scene.prompt
    assert person.base_traits in (await Scene.get(id=sibling.id)).prompt
