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
from services.creation_agent.production_resume import resume_production
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
async def test_user_retry_resets_unfinished_step_without_manual_review():
    task, _ = await failed_run()
    op = await AgentOperation.create(task=task, key='model:structured:Output:2', state='uncertain', external=True)
    await resume_production(task.id, AuthContext())
    await task.refresh_from_db(); await op.refresh_from_db()
    assert task.status == 6 and op.state == 'pending'


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
    await resume_production(task.id, AuthContext())
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
async def test_manual_retry_does_not_call_provider_review_endpoint():
    task, _ = await failed_run()
    operation = await AgentOperation.create(task=task, key='model:structured:Output:11', state='uncertain', external=True)
    with patch('httpx.AsyncClient.send', AsyncMock(side_effect=AssertionError('No receipt check required'))) as network:
        await resume_production(task.id, AuthContext())
        network.assert_not_awaited()
    await operation.refresh_from_db()
    assert operation.state == 'pending'


@pytest.mark.asyncio
async def test_running_task_is_not_reset_or_resubmitted():
    task, _ = await failed_run()
    await AiTask.filter(id=task.id).update(status=2)
    operation = await AgentOperation.create(task=task, key='media:image', state='running', external=True)
    current = await resume_production(task.id, AuthContext())
    await operation.refresh_from_db()
    assert current.status == 2 and operation.state == 'running'
