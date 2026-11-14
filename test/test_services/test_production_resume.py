import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4, uuid5

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from config import settings
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.creation_agent import AgentMessage, AgentConversation
from services.creation_agent.production_resume import resume_production, check_external_step
from services.creation_agent.run_recovery import checkpoint_inputs
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.operation_receipts import execute_step
from test.test_services.test_creation_agent_sessions import session_fixture


@pytest.fixture(autouse=True)
def no_auth(monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)


async def failed_run():
    conversation, _, model = await session_fixture()
    task = await AiTask.create(task_type=3, status=4, request_params={
        'workflow_version': 'agent-skills-v1', 'novel_id': conversation.novel_id,
        'assistant_model_config_id': model.id, 'prompt_language': 'zh'})
    message = await AgentMessage.create(task=task, conversation=conversation, role='assistant',
        request_id=uuid4(), request_hash='resume', events=[{'type': 'RUN_ERROR', 'message': 'Interrupted'}])
    await checkpoint_inputs({**task.request_params, 'task_id': str(task.id)})
    return task, message


@pytest.mark.asyncio
async def test_resume_reuses_original_receipts_and_double_click_does_not_generate_again():
    task, message = await failed_run()
    await AgentOperation.create(task=task, key='model:storyboard:Output:1', state='completed', external=True, result={'shots': [1, 2]})
    await AgentOperation.create(task=task, key='model:structured:Output:2', state='failed', external=True)
    a, b = await asyncio.gather(resume_production(task.id, AuthContext()), resume_production(task.id, AuthContext()))
    assert a.id == b.id == task.id
    await task.refresh_from_db()
    assert task.status == 6 and task.request_params['resume_count'] == 1
    await AiTask.filter(id=task.id).update(status=2)
    action = AsyncMock(return_value={'new': True})
    assert await execute_step(task.id, 'model:storyboard:Output:1', action, external=True) == {'shots': [1, 2]}
    action.assert_not_awaited()
    assert await execute_step(task.id, 'model:structured:Output:2', action, external=True) == {'new': True}
    action.assert_awaited_once()
    await message.refresh_from_db()
    events = await agent_event_log.load(message)
    assert events[message.run_input['stream_start_seq']]['type'] == 'RUN_STARTED'
    from services.creation_agent.production import finish_production_message
    task.status = 3
    await finish_production_message(task)
    assert (await agent_event_log.last(message))['type'] == 'RUN_FINISHED'


@pytest.mark.asyncio
async def test_uncertain_step_is_not_reset_when_audit_fails():
    task, _ = await failed_run()
    op = await AgentOperation.create(task=task, key='model:structured:Output:2', state='uncertain', external=True)
    with pytest.raises(HTTPException, match='结果待核对'):
        await resume_production(task.id, AuthContext())
    await task.refresh_from_db(); await op.refresh_from_db()
    assert task.status == 4 and op.state == 'uncertain'


@pytest.mark.asyncio
async def test_changed_inputs_or_another_active_run_block_resume():
    task, message = await failed_run()
    other = await AiTask.create(task_type=7, status=2)
    await AgentConversation.filter(id=message.conversation_id).update(active_task_id=other.id)
    with pytest.raises(HTTPException, match='会话正在运行'):
        await resume_production(task.id, AuthContext())
    await AgentConversation.filter(id=message.conversation_id).update(active_task_id=None)
    from models.chapter import Chapter
    await Chapter.filter(novel_id=task.request_params['novel_id']).update(name='Changed', updated_at=other.created_at)
    with pytest.raises(HTTPException, match='已变化'):
        await resume_production(task.id, AuthContext())


@pytest.mark.asyncio
async def test_resume_checks_write_permission_before_changing_any_receipts():
    task, _ = await failed_run()
    op = await AgentOperation.create(task=task, key='model:structured:Output:2', state='failed')
    with patch('auth.deps.require_roles', return_value=AsyncMock(side_effect=HTTPException(403, 'Denied'))):
        with pytest.raises(HTTPException) as denied:
            await resume_production(task.id, AuthContext())
    assert denied.value.status_code == 403
    await task.refresh_from_db(); await op.refresh_from_db()
    assert task.status == 4 and op.state == 'failed'


@pytest.mark.asyncio
async def test_resume_retries_only_missing_step_after_receipt_check():
    task, _ = await failed_run()
    kept = await AgentOperation.create(task=task, key='model:storyboard:Output:1', state='completed', result={'shots': [1]})
    missing = await AgentOperation.create(task=task, key='model:structured:Output:11', state='uncertain', external=True)
    with patch('services.creation_agent.production_resume.check_external_step', AsyncMock()) as check:
        await resume_production(task.id, AuthContext())
        check.assert_awaited_once()
        assert check.await_args.args[1].id == missing.id
    await kept.refresh_from_db(); await missing.refresh_from_db()
    assert kept.state == 'completed' and kept.result == {'shots': [1]}
    assert missing.state == 'pending'
    audit = await AgentOperation.get(task=task, key=f'resume:retry:{missing.id}:1')
    assert audit.result['operation_key'] == missing.key


@pytest.mark.asyncio
async def test_catalog_refresh_and_project_touch_do_not_invalidate_identical_production_inputs():
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    from models.chapter import Chapter
    from models.novel import Novel
    from models.config import AiModelConfig
    from models.studio_call import StudioCall
    from services.creation_agent.direct_plan import prepare_direct_plan
    from services.creation_agent.production_resume import validate_resume_inputs

    task, message = await failed_run()
    model = await AiModelConfig.get(id=task.request_params['assistant_model_config_id'])
    chapter = await Chapter.get(novel_id=task.request_params['novel_id'])
    task.request_params.update(chapter_id=chapter.id, task_id=str(task.id))
    await AgentMessage.create(task=task, conversation_id=message.conversation_id, role='user',
        request_id=message.request_id, request_hash='source', content='生成分镜')
    await prepare_direct_plan(task, SimpleNamespace(params=task.request_params))
    message.model_snapshot = {'id': model.id, 'model': model.model, 'pricing': model.pricing}
    await message.save()
    operation = await AgentOperation.create(task=task, key='model:storyboard:Output:1', state='completed')
    child = await AiTask.create(id=uuid5(task.id, operation.key), task_type=7, status=3)
    child_message = await AgentMessage.create(task=child, conversation_id=message.conversation_id, role='assistant',
        request_id=uuid4(), request_hash='child')
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    await StudioCall.create(request_key=uuid4(), usage_record_id=1, model_config_id=model.id,
        message_id=child_message.id, base_url=model.base_url.rstrip('/'), billing_mode='team', multiplier=1, next_check_at=now)
    await AiModelConfig.filter(id=model.id).update(updated_at=now)
    await Novel.filter(id=chapter.novel_id).update(updated_at=now)
    await validate_resume_inputs(task, message, [operation])
    await AiModelConfig.filter(id=model.id).update(model='different-model')
    with pytest.raises(HTTPException):
        await validate_resume_inputs(task, message, [operation])
    await AiModelConfig.filter(id=model.id).update(model=model.model)
    await Chapter.filter(id=chapter.id).update(content='changed source')
    with pytest.raises(HTTPException):
        await validate_resume_inputs(task, message, [operation])


@pytest.mark.asyncio
@pytest.mark.parametrize('status,settlement,allowed', [('completed', 'settled', True), ('completed', 'pending', False), ('submitted', 'pending', False), ('rejected', 'not_charged', True)])
async def test_finished_missing_results_can_retry_but_inflight_requests_cannot(status, settlement, allowed):
    from types import SimpleNamespace
    task, message = await failed_run()
    op = await AgentOperation.create(task=task, key='model:structured:Output:2', state='uncertain', external=True)
    child = await AgentMessage.create(task_id=(await AiTask.create(id=uuid5(task.id, op.key), task_type=7, status=4)).id,
        conversation_id=message.conversation_id, role='assistant', request_id=uuid4(), request_hash='child',
        usage={'calls': [{'status': 'failed', 'studio_call_id': 1}]})
    receipt_id = uuid4()
    row = SimpleNamespace(model_config_id=1, base_url='https://example.invalid/v1', platform_request_id=receipt_id)
    config = SimpleNamespace(base_url=row.base_url, api_key='fake')
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'id': str(receipt_id), 'model': 'test',
        'status': status, 'usage': {}, 'pricing': {}, 'settlement': {'status': settlement, 'amount': '0.14'}})
    client = AsyncMock(); client.get.return_value = response
    with patch('models.studio_call.StudioCall.get_or_none', AsyncMock(return_value=row)), \
         patch('models.config.AiModelConfig.get_or_none', AsyncMock(return_value=config)), \
         patch('httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value = client
        if allowed:
            await check_external_step(task, op)
        else:
            with pytest.raises(HTTPException):
                await check_external_step(task, op)
        client.get.assert_awaited_once()
        assert not client.post.called
    await op.refresh_from_db()
    assert op.state == 'uncertain'
