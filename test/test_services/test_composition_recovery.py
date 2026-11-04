import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.usage_record import ModelUsageRecord
from services.creation_agent.composition import CompositionHandler, submit_composition
from services.creation_agent.recovery import ProductionRecovery
from services.creation_agent.submissions import submission
from test.test_services.test_skill_workflow import enabled_project


@pytest.mark.asyncio
async def test_local_composition_failure_is_definite_and_does_not_require_provider_review():
    task = await AiTask.create(task_type=4, status=2, request_params={
        'workflow_version': 'agent-skills-v1', 'operation': 'compose', 'chapter_id': 1,
    })
    handler = CompositionHandler()
    with patch('controllers.video.video_controller._compose_chapter', AsyncMock(side_effect=RuntimeError('merge failed'))):
        with pytest.raises(RuntimeError, match='merge failed'):
            await handler.execute({**task.request_params, 'task_id': str(task.id)})
    row = await AgentOperation.get(task=task, key='media:compose')
    assert row.external is False and row.state == 'failed'


@pytest.mark.asyncio
async def test_completed_composition_receipt_is_reused_without_composing_twice():
    task = await AiTask.create(task_type=4, status=2, request_params={'operation': 'compose'})
    action = AsyncMock(return_value={'merged_url': '/media/episode.mp4'})
    with patch('controllers.video.video_controller._compose_chapter', action):
        params = {'task_id': str(task.id), 'chapter_id': 1}
        assert await CompositionHandler().execute(params) == await CompositionHandler().execute(params)
    action.assert_awaited_once()
    assert (await AgentOperation.get(task=task, key='media:compose')).external is False


@pytest.mark.asyncio
async def test_retry_of_legacy_uncertain_composition_reuses_the_task_and_keeps_an_audit():
    novel, chapter, _ = await enabled_project()
    receipt = {'submission_id': str(uuid4()), 'submission_hash': 'same-merge'}
    token = submission.set(receipt)
    try:
        task = await submit_composition(chapter.id)
        await AiTask.filter(id=task.id).update(status=4, stage='needs_review', error_message='提交结果待核对，系统不会重复提交')
        await AgentOperation.create(task=task, key='media:compose', state='running', external=True)
        first, second = await asyncio.gather(submit_composition(chapter.id), submit_composition(chapter.id))
        assert first.id == second.id == task.id
        await task.refresh_from_db()
        row = await AgentOperation.get(task=task, key='media:compose')
        assert task.status == 6 and task.stage == 'resuming' and task.error_message is None
        assert row.state == 'pending' and row.external is False
        assert task.request_params['composition_recovery']['previous_stage'] == 'needs_review'
        assert await AiTask.all().count() == 1
    finally:
        submission.reset(token)


@pytest.mark.asyncio
async def test_retry_never_resets_an_uncertain_paid_media_operation():
    novel, chapter, _ = await enabled_project()
    token = submission.set({'submission_id': str(uuid4()), 'submission_hash': 'different-step'})
    try:
        task = await submit_composition(chapter.id)
        await AiTask.filter(id=task.id).update(status=4, stage='needs_review')
        await AgentOperation.create(task=task, key='media:compose', state='uncertain', external=True)
        paid = await AgentOperation.create(task=task, key='media:image', state='uncertain', external=True)
        await submit_composition(chapter.id)
        await task.refresh_from_db(); await paid.refresh_from_db()
        assert task.status == 4 and paid.external is True and paid.state == 'uncertain'
    finally:
        submission.reset(token)


@pytest.mark.asyncio
async def test_restart_resumes_local_composition_but_preserves_unknown_provider_submission():
    local = await AiTask.create(task_type=4, status=2, request_params={'workflow_version': 'agent-skills-v1', 'operation': 'compose'})
    paid = await AiTask.create(task_type=4, status=2, request_params={'workflow_version': 'agent-skills-v1', 'operation': 'video'})
    await AgentOperation.create(task=local, key='media:compose', state='running', external=False)
    await AgentOperation.create(task=paid, key='media:video', state='running', external=True)
    await ProductionRecovery().recover()
    await local.refresh_from_db(); await paid.refresh_from_db()
    assert local.status == 6 and local.stage == 'resuming'
    assert (await AgentOperation.get(task=local)).state == 'pending'
    assert paid.status == 4 and paid.stage == 'needs_review'


@pytest.mark.asyncio
async def test_download_api_recovers_the_same_legacy_task_and_replays_its_result_without_charging(client):
    novel, chapter, _ = await enabled_project()
    identifier = str(uuid4())
    params = {'submission_id': identifier, 'submission_hash': 'placeholder'}
    from hashlib import sha256
    import json
    body = json.dumps({'chapter_id': chapter.id}, separators=(',', ':')).encode()
    params['submission_hash'] = sha256(json.dumps(['POST', '/api/video/merge', '']).encode() + b'\0' + body).hexdigest()
    token = submission.set(params)
    try:
        task = await submit_composition(chapter.id)
    finally:
        submission.reset(token)
    await AiTask.filter(id=task.id).update(status=4, stage='needs_review')
    await AgentOperation.create(task=task, key='media:compose', state='running', external=True)
    result = {'chapter_id': chapter.id, 'merged_url': '/media/complete.mp4', 'video_count': 2, 'total_duration': 4}
    compose = AsyncMock(return_value=result)
    with patch('controllers.video.video_controller._compose_chapter', compose):
        for _ in range(2):
            response = await client.post('/api/video/merge', content=body, headers={
                'X-Creation-Request-Id': identifier, 'Content-Type': 'application/json',
            })
            assert response.json()['code'] == 0, response.text
            assert response.json()['data']['merged_url'] == '/media/complete.mp4'
    compose.assert_awaited_once()
    await task.refresh_from_db()
    assert task.status == 3 and task.stage == 'completed'
    assert await AiTask.filter(task_type=4).count() == 1
    assert await ModelUsageRecord.all().count() == 0


@pytest.mark.asyncio
async def test_cancelled_composition_is_never_resurrected_by_a_retry():
    novel, chapter, _ = await enabled_project()
    token = submission.set({'submission_id': str(uuid4()), 'submission_hash': 'cancelled'})
    try:
        task = await submit_composition(chapter.id)
        await AiTask.filter(id=task.id).update(status=5, stage='cancelled')
        row = await AgentOperation.create(task=task, key='media:compose', state='running', external=True)
        await submit_composition(chapter.id)
        await task.refresh_from_db(); await row.refresh_from_db()
        assert task.status == 5 and row.state == 'running' and row.external is True
    finally:
        submission.reset(token)
