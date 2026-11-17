"""Separate extraction and semantic review requests on the existing task boundary."""

from dataclasses import replace
from models.story_memory import StoryFact, StorySubject
from prompts.story_memory import contract, method
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.strict_text import require_text_execution
from services.story_memory.sources import parent_state, verify_inputs
from services.story_memory.store import get_commit, save_candidate, save_review


async def review(execution, commit, context):
    stage = replace(execution, params={**execution.params, 'output_contract': contract('review'),
        'creative_method': method(execution.params['creative_method'], 'review', execution.language)})
    revision, candidate_hash = commit.revision, fingerprint(commit.candidate)
    result = await stage.generate_strict({**context, 'candidate': commit.candidate})
    async def persist():
        await execution.before_request()
        saved = await save_review(commit.novel_id, commit.id, revision, candidate_hash, result,
            task_id=execution.params['task_id'])
        return {'commit_id': saved.id, 'status': saved.status, 'revision': saved.revision}
    return await execute_step(execution.params['task_id'], 'persist:story-memory-review', persist, atomic=True)


async def analyze(params):
    execution = require_text_execution(params)
    commit = await get_commit(params['novel_id'], params['story_commit_id'])
    await verify_inputs(commit)
    from services.story_memory.sources import conflict
    if commit.revision != params['story_revision']:
        conflict('候选版本已变化，请重新审核')
    state = await parent_state(commit)
    facts = await StoryFact.filter(novel_id=commit.novel_id, id__in=state['fact_ids']).order_by('id').values(
        'id', 'subject_id', 'category', 'nature', 'content', 'scope')
    subjects = await StorySubject.filter(novel_id=commit.novel_id).order_by('id').values('id', 'kind', 'name', 'aliases')
    context = {'source_snapshot': commit.source_snapshot, 'prior_state': state,
        'prior_facts': facts, 'subjects': subjects}
    if params['operation'] == 'story_memory_analyze':
        result = await execution.generate_strict(context)
        async def persist():
            await execution.before_request()
            saved = await save_candidate(commit.novel_id, commit.id, result, params['story_revision'], initial=True)
            return {'commit_id': saved.id}
        await execute_step(params['task_id'], 'persist:story-memory-candidate', persist, atomic=True)
        commit = await get_commit(commit.novel_id, commit.id)
    return await review(execution, commit, context)
