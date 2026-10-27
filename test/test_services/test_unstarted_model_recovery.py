"""Old local preflight errors must not permanently block a project's retry button."""
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid5

import pytest

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from models.usage_record import ModelUsageRecord
from services.creation_agent.production import conversation_for_task
from services.creation_agent.skill_execution import prepare_workflow
from test.test_services.test_skill_workflow import enabled_project


async def rejected_story():
    novel, _, _ = await enabled_project()
    novel.content = '第1章 开始\nAlex waits.'
    await novel.save()
    params = await prepare_workflow({'novel_id': novel.id, 'prompt_language': 'zh'})
    parent = await AiTask.create(task_type=5, status=4, stage='needs_review',
        request_params=params, error_message='外部请求结果待核对，系统不会自动重试')
    assistant = await conversation_for_task(parent)
    key = 'model:story:BookAnalysis:'
    child = await AiTask.create(id=uuid5(parent.id, key), task_type=7, status=4,
        request_params={**params, 'parent_task_id': str(parent.id)})
    message = await AgentMessage.create(conversation_id=assistant.conversation_id, task=child,
        role='assistant', request_id=child.id, request_hash=str(child.id),
        run_input={'internal_production_step': True}, usage={})
    receipt = await AgentOperation.create(task=parent, key=key, state='uncertain', external=True)
    return novel, parent, child, message, receipt


@pytest.mark.asyncio
async def test_analysis_api_admits_a_fresh_task_after_a_proven_unstarted_failure(client, monkeypatch):
    novel, old, child, message, receipt = await rejected_story()
    run = AsyncMock()
    monkeypatch.setattr('api.novel.ai_task_executor.run', run)
    response = await client.post(f'/api/novel/{novel.id}/analyze', headers={'X-Creation-Request-Id': 'db757eba-4d4a-42e3-8e98-3de44d0f1fd4'})
    body = response.json()
    assert body['code'] == 0, body
    assert body['data']['id'] != str(old.id)
    assert body['data']['status'] in (1, 6)
    created = await AiTask.get(id=body['data']['id'])
    assert created.request_params['agent_configuration']['max_context_characters'] is None
    run.assert_awaited_once()
    assert str(run.await_args.args[0].id) == body['data']['id']
    await old.refresh_from_db()
    await receipt.refresh_from_db()
    assert old.status == 4 and old.stage == 'failed'
    assert '未发出' in old.error_message
    assert receipt.state == 'failed'
    audit = await AgentOperation.get(task=old, key='reconcile:unstarted_model')
    assert audit.result['previous_error'] == '外部请求结果待核对，系统不会自动重试'
    assert audit.result['steps'][0]['child_task_id'] == str(child.id)
    assert audit.result['steps'][0]['previous_state'] == 'uncertain'
    assert await ModelUsageRecord.all().count() == 0
    replay = (await client.post(f'/api/novel/{novel.id}/analyze', headers={'X-Creation-Request-Id': 'db757eba-4d4a-42e3-8e98-3de44d0f1fd4'})).json()
    assert replay['data']['id'] == body['data']['id']
    assert await AiTask.filter(task_type=5).count() == 2
    assert await AgentOperation.filter(task=old, key='reconcile:unstarted_model').count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('evidence', ['started', 'missing_child', 'missing_message', 'running_child', 'wrong_parent', 'native_result', 'media', 'completed_external', 'ledger'])
async def test_analysis_api_keeps_genuine_or_unverifiable_external_uncertainty_blocked(client, monkeypatch, evidence):
    novel, parent, child, message, receipt = await rejected_story()
    if evidence == 'started':
        message.usage = {'calls': [{'status': 'in_progress', 'usage_reported': False}], 'requests': 1}
        await message.save()
    elif evidence == 'missing_child':
        await child.delete()
    elif evidence == 'missing_message':
        await message.delete()
    elif evidence == 'running_child':
        child.status = 2
        await child.save()
    elif evidence == 'wrong_parent':
        child.request_params['parent_task_id'] = 'other-task'
        await child.save()
    elif evidence == 'native_result':
        message.native_messages = [{'result': 'already returned'}]
        await message.save()
    elif evidence == 'media':
        receipt.key = 'media:cover'
        await receipt.save()
    elif evidence == 'completed_external':
        await AgentOperation.create(task=parent, key='media:cover', state='completed', external=True)
    else:
        await ModelUsageRecord.create(novel_id=novel.id, ai_task_id=child.id, task_type=7,
            billing_type='text', model='test', usage={'input_tokens': 10}, cost=0.01)
    original = deepcopy(receipt.result)
    run = AsyncMock()
    monkeypatch.setattr('api.novel.ai_task_executor.run', run)
    response = await client.post(f'/api/novel/{novel.id}/analyze')
    assert response.json()['code'] == 409
    run.assert_not_awaited()
    await parent.refresh_from_db()
    await receipt.refresh_from_db()
    assert parent.stage == 'needs_review'
    assert receipt.state == 'uncertain' and receipt.result == original
    assert not await AgentOperation.filter(task=parent, key='reconcile:unstarted_model').exists()
    assert await AiTask.filter(task_type=5).count() == 1


@pytest.mark.asyncio
async def test_parallel_reconciliation_preserves_one_audit_and_never_runs_the_model():
    import asyncio
    from services.creation_agent.preflight_recovery import reconcile_unstarted_model_task
    _, parent, _, _, _ = await rejected_story()
    assert await asyncio.gather(reconcile_unstarted_model_task(parent), reconcile_unstarted_model_task(parent)) == [True, True]
    assert await AgentOperation.filter(task=parent, key='reconcile:unstarted_model').count() == 1
    assert await AiTask.filter(task_type=5).count() == 1
