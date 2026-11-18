"""Separate extraction and semantic review requests on the existing task boundary."""

from dataclasses import replace
from models.agent_operation import AgentOperation
from models.story_memory import StoryFact, StorySubject
from schemas.story_memory import StoryReview
from prompts.story_memory import contract, method
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.strict_text import require_text_execution
from services.story_memory.sources import conflict, parent_state, verify_inputs
from services.story_memory.evidence import anchor_evidence
from services.story_memory.store import get_commit, save_candidate, save_repaired_candidate, save_review, validate_candidate


async def review(execution, commit, context, *, repaired=None):
    stage = replace(execution, params={**execution.params, 'output_contract': contract('review'),
        'creative_method': method(execution.params['creative_method'], 'review', execution.language)})
    candidate = commit.candidate if repaired is None else repaired
    revision, candidate_hash = commit.revision, fingerprint(candidate)
    result = await stage.generate_strict({**context, 'candidate': candidate})
    async def persist():
        await execution.before_request()
        task_id = execution.params['task_id']
        if repaired is None:
            saved = await save_review(commit.novel_id, commit.id, revision, candidate_hash, result, task_id=task_id)
        else:
            saved = await save_repaired_candidate(commit.novel_id, commit.id, execution.params['story_package_hash'],
                repaired, result, task_id=task_id)
        return {'commit_id': saved.id, 'status': saved.status, 'revision': saved.revision}
    return await execute_step(execution.params['task_id'], 'persist:story-memory-review', persist, atomic=True)


async def analyze(params):
    execution = require_text_execution(params)
    repair = params['operation'] == 'story_memory_repair'
    if repair:
        saved = await AgentOperation.get_or_none(task_id=params['task_id'], key='persist:story-memory-review', state='completed')
        if saved is not None:
            return saved.result
    commit = await get_commit(params['novel_id'], params['story_commit_id'])
    await verify_inputs(commit)
    if commit.revision != params['story_revision']:
        conflict('候选版本已变化，请重新审核')
    state = await parent_state(commit)
    facts = await StoryFact.filter(novel_id=commit.novel_id, id__in=state['fact_ids']).order_by('id').values(
        'id', 'subject_id', 'category', 'nature', 'content', 'scope')
    subjects = await StorySubject.filter(novel_id=commit.novel_id).order_by('id').values('id', 'kind', 'name', 'aliases')
    context = {'source_snapshot': commit.source_snapshot, 'prior_state': state,
        'prior_facts': facts, 'subjects': subjects}
    if repair:
        if commit.status != 'needs_review' or commit.package_hash != params['story_package_hash']:
            conflict('候选或审核已变化，补全结果不能使用')
        findings = [issue for issue in commit.review['issues'] if issue['severity'] == 'blocking']
        result = await execution.generate_strict({**context, 'original_candidate': commit.candidate, 'review_findings': findings})
        candidate = await validate_candidate(commit, anchor_evidence(result, commit.source_snapshot))
        return await review(execution, commit, context, repaired=candidate.model_dump(mode='json'))
    if commit.replaces_id:
        previous = await get_commit(commit.novel_id, commit.replaces_id)
        context['previous_commit'] = {'id': previous.id, 'source_snapshot': previous.source_snapshot,
            'candidate': previous.candidate, 'review': {
                key: value for key, value in previous.review.items() if key in StoryReview.model_fields}}
    if params['operation'] == 'story_memory_analyze':
        result = anchor_evidence(await execution.generate_strict(context), commit.source_snapshot)
        async def persist():
            await execution.before_request()
            saved = await save_candidate(commit.novel_id, commit.id, result, params['story_revision'], initial=True)
            return {'commit_id': saved.id}
        await execute_step(params['task_id'], 'persist:story-memory-candidate', persist, atomic=True)
        commit = await get_commit(commit.novel_id, commit.id)
    return await review(execution, commit, context)
