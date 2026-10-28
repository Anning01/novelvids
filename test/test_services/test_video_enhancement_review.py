"""Enhancement closure preserves late evidence and never replays paid work."""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from models.agent_operation import AgentOperation
from schemas.ai_task import TaskReviewResolution
from services.creation_agent.operation_receipts import SubmissionUncertain, execute_step
from services.creation_agent.review import close_uncertain_task
from services.video_enhancement.settlement import settle_enhancement
from test.test_services.test_skill_workflow import enabled_project
from test.test_services.test_video_enhancement_billing import completed_export


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['not_submitted', 'provider_failed'])
async def test_late_processing_evidence_reopens_conflicting_review_without_rebilling(outcome):
    novel, chapter, _ = await enabled_project()
    task, export = await completed_export(novel_id=novel.id, chapter_id=chapter.id)
    completed = dict(export.provider_result)
    export.provider_task_id = None
    export.provider_result = {}
    export.submission_slot = True
    await export.save()
    task.status = 4
    task.stage = 'needs_review'
    await task.save()
    await AgentOperation.create(task=task, key='media:enhance_export', state='uncertain', external=True)
    resolution = TaskReviewResolution(outcome=outcome, note='Checked provider records for the lost response.')
    await close_uncertain_task(task.id, resolution, user_id=1)
    await export.refresh_from_db()
    assert export.collection_complete and not export.submission_slot
    export.provider_task_id = 'late-provider-id'
    export.provider_result = completed
    await export.save()
    first = await settle_enhancement(task, export)
    again = await settle_enhancement(task, export)
    await task.refresh_from_db()
    assert first.id == again.id and again.cost == Decimal('0.416667')
    assert task.stage == 'needs_review'
    assert task.request_params['review_conflict'] is True
    evidence_id = task.request_params['review_evidence']['id']
    await close_uncertain_task(task.id, resolution, user_id=1)
    await task.refresh_from_db()
    assert task.request_params['review_evidence']['id'] == evidence_id
    assert task.stage == 'needs_review'
    with pytest.raises(HTTPException):
        await close_uncertain_task(task.id, TaskReviewResolution(outcome=outcome, note='Old conclusion', evidence_id=evidence_id))
    await close_uncertain_task(task.id, TaskReviewResolution(outcome='completed_unrecoverable', note='Late success confirmed; media unavailable.', evidence_id=evidence_id))
    await task.refresh_from_db()
    assert task.request_params['review_conflict'] is False
    assert (await settle_enhancement(task, export)).cost == first.cost
    task.status = 2
    await task.save()
    action = AsyncMock()
    with pytest.raises(SubmissionUncertain):
        await execute_step(task.id, 'media:enhance_export', action, external=True)
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_processing_task_requires_query_before_manual_closure():
    novel, chapter, _ = await enabled_project()
    task, export = await completed_export(novel_id=novel.id, chapter_id=chapter.id)
    export.provider_result = {'status':'running'}
    await export.save()
    task.status = 4
    task.stage = 'needs_review'
    await task.save()
    with pytest.raises(HTTPException) as error:
        await close_uncertain_task(task.id, TaskReviewResolution(outcome='not_submitted', note='Cannot override accepted ID.'))
    assert error.value.status_code == 409
    assert await AgentOperation.filter(task=task, key='review:closure').count() == 0
