"""Prepare reusable story snapshots for novels with a recorded multi-chapter split."""

import logging
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.story_memory import StoryCommit, StoryMemoryProject
from schemas.story_memory import StoryAnalysisRequest, StoryDecision
from services.ai_task_executor import WaitingForDependencies, ai_task_executor
from services.creation_agent.plan_sources import fingerprint
from services.creation_objects import ACTIVE_TASK_STATUSES, project_write
from services.story_memory.sources import latest_commit, predecessor, source_snapshot
from services.story_memory.status import memory_status
from services.story_memory.store import CANDIDATE_STATUSES, decide

logger = logging.getLogger(__name__)


async def enabled(novel_id):
    return await StoryMemoryProject.filter(novel_id=novel_id).exists()


async def queue_memory(novel_id, chapter_id, ctx, *, model_id=None):
    """Return the single durable task for this source version, if it needs work."""
    from controllers.story_memory import submit_analysis
    from services.creation_agent.submissions import submission

    try:
        async with project_write(novel_id):
            state = await memory_status(novel_id)
            if not state['automatic']:
                return None
            scope = state['baseline'] if chapter_id is None else next(
                (row for row in state['chapters'] if row['chapter_id'] == chapter_id), None)
            if scope is None or scope['state'] == 'current' or not scope['can_analyze']:
                return None
            parent_id = await predecessor(novel_id, chapter_id)
            previous = await latest_commit(novel_id, chapter_id)
            replaced_id = previous.id if previous else None
            source_hash = fingerprint(await source_snapshot(novel_id, chapter_id))
            commits = await StoryCommit.filter(novel_id=novel_id, chapter_id=chapter_id,
                source_hash=source_hash, parent_id=parent_id, replaces_id=replaced_id).order_by('-id')
            for commit in commits:
                if commit.status in CANDIDATE_STATUSES:
                    await decide(novel_id, commit.id, StoryDecision(decision='accept',
                        expected_package_hash=commit.package_hash), None)
                    return None
                if commit.status == 'pending' and commit.task_id:
                    child = await AiTask.get_or_none(id=commit.task_id)
                    if child and child.status in ACTIVE_TASK_STATUSES:
                        return child
            invalidated_id = next((commit.id for commit in commits if commit.status == 'stale'), None)
            edition = fingerprint([novel_id, chapter_id, source_hash, parent_id, replaced_id, invalidated_id])
            request_id = uuid5(NAMESPACE_URL, f'novelvids:story-memory:{edition}')
            prior_attempt = next((commit for commit in commits if commit.request_id == request_id), None)
            if prior_attempt:
                return None
            request = StoryAnalysisRequest(request_id=request_id, chapter_id=chapter_id,
                assistant_model_config_id=model_id, skill_id=0)
            token = submission.set(None)
            try:
                return await submit_analysis(novel_id, request, ctx, automatic=True)
            finally:
                submission.reset(token)
    except HTTPException as error:
        # Story memory is supplementary. A missing model, balance or usable source cannot block production.
        logger.info('Story memory unavailable: novel_id=%s chapter_id=%s code=%s', novel_id, chapter_id, error.status_code)
        return None


async def prepare_for_generation(execution, chapter_id):
    from services.creation_agent.handler import authorize_run

    params = execution.params
    novel_id = params['novel_id']
    ctx = await authorize_run(params)
    model_id = params.get('assistant_model_config_id')
    for scope in (None, chapter_id):
        await execution.before_request()
        child = await queue_memory(novel_id, scope, ctx, model_id=model_id)
        if child is None:
            continue
        await AgentOperation.get_or_create(task_id=params['task_id'], key=f'submit:story-memory:{child.id}',
            defaults={'state': 'completed', 'result': {'task_id': str(child.id)}})
        await ai_task_executor.run(child)
        await child.refresh_from_db()
        if child.status in ACTIVE_TASK_STATUSES:
            raise WaitingForDependencies()
        if child.status == 3 and not child.request_params.get('automatic_story_memory'):
            await queue_memory(novel_id, scope, ctx, model_id=model_id)
