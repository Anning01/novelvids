from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from models.ai_task import AiTask
from models.config import AiModelConfig
from models.scene import Scene
from models.novel import Novel
from models.agent_operation import AgentOperation
from schemas.storyboard_sheet import SheetEditRequest, SheetRestoreRequest
from services.storyboard.sheets import submit_sheet_edit, execute_sheet_edit, scene_fingerprint
from services.storyboard.sheet_history import sheet_history, sheet_revision, restore_sheet
from services.creation_agent.submissions import submission
from test.test_services.test_creation_agent_sessions import session_fixture


async def fixture(monkeypatch):
    conversation, request, _ = await session_fixture()
    scene = await Scene.get(chapter__novel_id=conversation.novel_id)
    await Novel.filter(id=conversation.novel_id).update(storyboard_enabled=True)
    config = await AiModelConfig.create(task_type=2, name='test-sheet', model='test-sheet', image_model_type='gpt_image_2',
        api_protocol='openai_compatible', base_url='https://example.invalid', api_key='test', is_active=True)
    old = await AiTask.create(task_type=2,status=3,request_params={'operation':'storyboard_sheet','scene_id':scene.id,
        'novel_id':conversation.novel_id,'model_config_id':config.id,'sheet':{'image_prompt':'原来的完整线稿提示词','video_prompt':scene.prompt}},
        response_data={'images':['/media/old.png'],'saved':True})
    scene.metadata = {'keep':'keep', 'storyboard_sheet_excluded':True, 'storyboard_sheet':{
        'task_id':str(old.id),'status':'completed','image_url':'/media/old.png','video_prompt':scene.prompt,
        'video_guidance':'原视频指导','scene_fingerprint':scene_fingerprint(scene)}}
    await scene.save()
    generate=AsyncMock(return_value=[SimpleNamespace(url='https://example.invalid/result.png')])
    monkeypatch.setattr('services.reference.generator.generate_for_sora_consistency', generate)
    monkeypatch.setattr('services.image_inputs.resolve_reference_images', lambda values: ['resolved:'+value for value in values])
    monkeypatch.setattr('services.reference.handler._persist_generated_image', AsyncMock(return_value='/media/new.png'))
    return scene, config, old, generate, request


async def run(task):
    await AiTask.filter(id=task.id).update(status=2)
    result=await execute_sheet_edit({**task.request_params,'task_id':str(task.id)})
    await AiTask.filter(id=task.id).update(status=3,response_data=result)
    return result


@pytest.mark.asyncio
async def test_edit_sends_original_image_prompt_and_instruction_preserving_scene_then_restores(monkeypatch):
    scene, _, old, generate, _ = await fixture(monkeypatch)
    before=(scene.prompt,scene.description,scene.prompt_params)
    task=await submit_sheet_edit(scene.id, SheetEditRequest(instruction='只调整第二格站位',expected_revision=sheet_revision(scene)))
    result=await run(task)
    assert result['saved'] and result['input_image_count']==1
    args=generate.call_args
    assert args.kwargs['reference_images']==['resolved:/media/old.png']
    assert '原来的完整线稿提示词' in args.args[0]['base_traits'] and '只调整第二格站位' in args.args[0]['base_traits']
    await scene.refresh_from_db()
    assert (scene.prompt,scene.description,scene.prompt_params)==before
    assert scene.metadata['keep']=='keep' and scene.metadata['storyboard_sheet_excluded'] is True
    history=await sheet_history(scene.id)
    assert {r['image_url'] for r in history['items']}=={'/media/new.png','/media/old.png'}
    assert sum(r['is_current'] for r in history['items'])==1
    assert next(r for r in history['items'] if r['image_url']=='/media/old.png')['task_id']==str(old.id)
    assert not any(r['source'] for r in history['items'])
    scene=await restore_sheet(scene.id, SheetRestoreRequest(task_id=old.id,expected_revision=history['revision']))
    assert scene.metadata['storyboard_sheet']['image_url']=='/media/old.png'
    assert generate.await_count==1
    assert len((await sheet_history(scene.id))['items'])==2


@pytest.mark.asyncio
async def test_duplicate_submission_and_replay_do_not_repeat_external_generation(monkeypatch):
    scene, _, _, generate, _=await fixture(monkeypatch)
    payload=SheetEditRequest(instruction='调亮线条',expected_revision=sheet_revision(scene))
    token=submission.set({'submission_id':str(uuid4()),'submission_hash':'same-request'})
    try:
        task=await submit_sheet_edit(scene.id,payload)
        duplicate=await submit_sheet_edit(scene.id,payload)
        assert duplicate.id==task.id
        first=await run(task)
        again=await execute_sheet_edit({**task.request_params,'task_id':str(task.id)})
        assert again==first and generate.await_count==1
        assert (await submit_sheet_edit(scene.id,payload)).id==task.id
    finally:submission.reset(token)


@pytest.mark.asyncio
async def test_save_retry_reuses_generated_image(monkeypatch):
    scene,_,_,generate,_=await fixture(monkeypatch)
    task=await submit_sheet_edit(scene.id,SheetEditRequest(instruction='调整站位',expected_revision=sheet_revision(scene)))
    import services.storyboard.sheets as sheets
    apply=sheets.apply_sheet_result
    monkeypatch.setattr(sheets,'apply_sheet_result',AsyncMock(side_effect=RuntimeError('database unavailable')))
    with pytest.raises(RuntimeError):await run(task)
    assert (await AgentOperation.get(task=task,key='sheet:generate')).state=='completed'
    await AgentOperation.filter(task=task,key='sheet:apply').update(state='pending')
    monkeypatch.setattr(sheets,'apply_sheet_result',apply)
    assert (await run(task))['saved']
    assert generate.await_count==1


@pytest.mark.asyncio
async def test_provider_failure_keeps_old_image(monkeypatch):
    scene,_,_,generate,_=await fixture(monkeypatch)
    generate.side_effect=RuntimeError('provider failure')
    task=await submit_sheet_edit(scene.id,SheetEditRequest(instruction='调整站位',expected_revision=sheet_revision(scene)))
    with pytest.raises(RuntimeError):await run(task)
    await scene.refresh_from_db()
    assert scene.metadata['storyboard_sheet']['image_url']=='/media/old.png'
    assert (await AgentOperation.get(task=task,key='sheet:generate')).state=='uncertain'


@pytest.mark.asyncio
async def test_restore_during_generation_prevents_late_overwrite(monkeypatch):
    scene,_,old,generate,_=await fixture(monkeypatch)
    task=await submit_sheet_edit(scene.id,SheetEditRequest(instruction='调整站位',expected_revision=sheet_revision(scene)))
    async def respond(*args,**kwargs):
        await scene.refresh_from_db()
        await restore_sheet(scene.id,SheetRestoreRequest(task_id=old.id,expected_revision=sheet_revision(scene)))
        return [SimpleNamespace(url='https://example.invalid/new.png')]
    generate.side_effect=respond
    assert (await run(task))['saved'] is False
    await scene.refresh_from_db()
    assert scene.metadata['storyboard_sheet']['image_url']=='/media/old.png'
    assert any(r['image_url']=='/media/new.png' and not r['is_current'] for r in (await sheet_history(scene.id))['items'])


@pytest.mark.asyncio
async def test_legacy_image_without_original_task_is_preserved_as_source_snapshot(monkeypatch):
    scene,config,old,_,_=await fixture(monkeypatch)
    scene.metadata['storyboard_sheet'].pop('task_id')
    await scene.save()
    task=await submit_sheet_edit(scene.id,SheetEditRequest(instruction='调整站位',expected_revision=sheet_revision(scene),model_config_id=config.id))
    await run(task)
    await old.delete()  # Isolated test database: prove history does not depend on the old task.
    history=await sheet_history(scene.id)
    source=next(r for r in history['items'] if r['source'])
    restored=await restore_sheet(scene.id,SheetRestoreRequest(task_id=source['task_id'],source=True,expected_revision=history['revision']))
    assert restored.metadata['storyboard_sheet']['image_url']=='/media/old.png'


@pytest.mark.asyncio
async def test_stale_revision_missing_image_and_foreign_restore_are_rejected(monkeypatch):
    scene,config,old,generate,_=await fixture(monkeypatch)
    with pytest.raises(HTTPException):await submit_sheet_edit(scene.id,SheetEditRequest(instruction='改图',expected_revision='stale'))
    other=await Scene.create(chapter_id=scene.chapter_id,sequence=99)
    with pytest.raises(HTTPException):await restore_sheet(other.id,SheetRestoreRequest(task_id=old.id,expected_revision=sheet_revision(other)))
    with pytest.raises(HTTPException):await submit_sheet_edit(other.id,SheetEditRequest(instruction='改图',expected_revision=sheet_revision(other),model_config_id=config.id))
    assert generate.await_count==0


def test_edit_prompt_contract_and_language():
    from prompts.storyboard_sheet_edit import render_sheet_edit
    for language in ['zh','en']:
        text=render_sheet_edit('original prompt','change "panel 2"',language)
        assert 'original prompt' in text and 'panel 2' in text
        assert ('参考图1' if language=='zh' else 'reference image 1') in text
        assert ('逐字保留' if language=='zh' else 'verbatim') in text


@pytest.mark.asyncio
async def test_agent_model_selects_read_then_edit_tool_and_both_runtimes_expose_it(monkeypatch):
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, TextPart
    from services.creation_agent.runtime import creation_agent, CreationAgentDeps
    from services.creation_agent.changes import CreationChanges
    from services.creation_agent.deep_tools import business_tools
    from services.creation_agent.skill_execution import SkillExecution, prepare_workflow, current_execution
    scene,_,_,_,request=await fixture(monkeypatch)
    original_request='修改这个分镜的线稿，墓碑上要有字\n赵无指之墓\n无极宗第七一代宗主'
    request=request.model_copy(update={'message':original_request})
    await scene.fetch_related('chapter')
    params=await prepare_workflow({'novel_id':scene.chapter.novel_id,'chapter_id':scene.chapter_id})
    parent=await AiTask.create(task_type=7,status=2,request_params=params)
    service=CreationChanges(novel_id=scene.chapter.novel_id,task_id=parent.id,request=request,max_batch_size=8)
    execution=SkillExecution({**params,'task_id':str(parent.id)},SimpleNamespace(id=999999,usage={}),AsyncMock())
    token=current_execution.set(execution)
    deps=CreationAgentDeps(service=None,changes=service,context={})
    calls=0
    def respond(messages,info):
        nonlocal calls
        calls+=1
        names={tool.name for tool in info.function_tools}
        assert {'read_storyboard_sheet','edit_storyboard_sheet'}<=names
        edit_tool=next(tool for tool in info.function_tools if tool.name=='edit_storyboard_sheet')
        assert 'instruction' not in edit_tool.parameters_json_schema['properties']
        if calls==1:return ModelResponse(parts=[ToolCallPart('read_storyboard_sheet',{'scene_id':scene.id},tool_call_id='read-sheet')])
        if calls==2:
            context=[part.content for message in messages for part in message.parts if isinstance(part,ToolReturnPart)][-1]
            assert context['has_current_image'] is True
            assert 'image_url' not in str(context) and '/media/' not in str(context)
            return ModelResponse(parts=[ToolCallPart('edit_storyboard_sheet',{'scene_id':scene.id,'expected_revision':context['revision'],'instruction':'错误转述：赵无垢之墓，无极宗第七十一代宗主'},tool_call_id='edit-sheet')])
        return ModelResponse(parts=[TextPart('已提交线稿修改任务。')])
    try:
        model=FunctionModel(respond)
        await creation_agent.run(request.message,model=model,deps=deps)
        receipts=await AgentOperation.filter(task=parent,key__startswith='submit:sheet-edit:')
        assert len(receipts)==1 and receipts[0].result['scene_id']==scene.id
        child=await AiTask.get(id=receipts[0].result['task_id'])
        assert child.request_params['edit_instruction']==original_request
        assert '赵无指之墓' in child.request_params['sheet']['image_prompt']
        assert '无极宗第七一代宗主' in child.request_params['sheet']['image_prompt']
        tools=await business_tools(deps,model,AsyncMock())
        assert {'read_storyboard_sheet','edit_storyboard_sheet'}<={tool.name for tool in tools}
        deps.changes=CreationChanges(novel_id=service.novel_id,task_id=parent.id,request=request.model_copy(update={'write_scope':'read_only'}),max_batch_size=8)
        tools=await business_tools(deps,model,AsyncMock())
        assert 'edit_storyboard_sheet' not in {tool.name for tool in tools}
    finally:current_execution.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('scope',['read_only','other_selected','other_chapter','foreign_project'])
async def test_agent_scope_rejects_unauthorized_sheet_edits(monkeypatch,scope):
    from services.creation_agent.changes import CreationChanges
    from services.creation_agent.sheet_tools import edit_sheet
    scene,_,_,generate,request=await fixture(monkeypatch)
    await scene.fetch_related('chapter')
    other=await Scene.create(chapter_id=scene.chapter_id,sequence=2)
    if scope=='read_only':request=request.model_copy(update={'write_scope':'read_only'})
    elif scope=='other_selected':request=request.model_copy(update={'targets':[],'write_scope':'selected'})
    elif scope=='other_chapter':request=request.model_copy(update={'targets':[],'write_scope':'chapter','chapter_id':999999})
    novel_id=999999 if scope=='foreign_project' else scene.chapter.novel_id
    service=CreationChanges(novel_id=novel_id,task_id=uuid4(),request=request,max_batch_size=8)
    with pytest.raises(ValueError):await edit_sheet(service,other.id,sheet_revision(scene))
    assert generate.await_count==0


@pytest.mark.asyncio
async def test_http_history_restore_and_edit_use_scoped_endpoints(monkeypatch,client):
    from services.ai_task_executor import ai_task_executor
    scene,_,old,_,_=await fixture(monkeypatch)
    monkeypatch.setattr(ai_task_executor,'run',AsyncMock())
    history=(await client.get(f'/api/scene/{scene.id}/storyboard-sheet/history')).json()['data']
    headers={'X-Creation-Request-Id':str(uuid4())}
    payload={'instruction':'调整第二格','expected_revision':history['revision']}
    first=(await client.post(f'/api/scene/{scene.id}/storyboard-sheet/edit',json=payload,headers=headers)).json()
    second=(await client.post(f'/api/scene/{scene.id}/storyboard-sheet/edit',json=payload,headers=headers)).json()
    assert first['code']==0 and first['data']['id']==second['data']['id']
    conflict=(await client.post(f'/api/scene/{scene.id}/storyboard-sheet/edit',json={**payload,'instruction':'different'},headers=headers)).json()
    assert conflict['code']==409
    await scene.refresh_from_db()
    restored=(await client.post(f'/api/scene/{scene.id}/storyboard-sheet/restore',json={'task_id':str(old.id),'expected_revision':sheet_revision(scene)})).json()
    assert restored['code']==0 and restored['data']['metadata']['storyboard_sheet']['image_url']=='/media/old.png'


@pytest.mark.asyncio
async def test_followup_edit_uses_current_image_without_recursively_wrapping_old_prompts(monkeypatch):
    scene,_,_,generate,_=await fixture(monkeypatch)
    first=await submit_sheet_edit(scene.id,SheetEditRequest(instruction='第一轮修改',expected_revision=sheet_revision(scene)))
    await run(first)
    await scene.refresh_from_db()
    second=await submit_sheet_edit(scene.id,SheetEditRequest(instruction='第二轮修改',expected_revision=sheet_revision(scene)))
    assert second.request_params['original_image_prompt']=='原来的完整线稿提示词'
    assert '第一轮修改' not in second.request_params['sheet']['image_prompt']
    await run(second)
    assert generate.call_args.kwargs['reference_images']==['resolved:/media/new.png']
