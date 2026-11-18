"""Extract one strict candidate and save it for confirmation."""

from models.story_memory import StoryFact, StorySubject
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.strict_text import require_text_execution
from services.story_memory.sources import conflict, parent_state, verify_inputs
from services.story_memory.store import get_commit, save_candidate


async def analyze(params):
    if params['operation'] != 'story_memory_analyze':
        conflict('候选可以直接确认入库')
    execution = require_text_execution(params)
    commit = await get_commit(params['novel_id'], params['story_commit_id'])
    await verify_inputs(commit)
    if commit.revision != params['story_revision']:
        conflict('候选版本已变化，请重新读取')
    state = await parent_state(commit)
    facts = await StoryFact.filter(novel_id=commit.novel_id, id__in=state['fact_ids']).order_by('id').values(
        'id', 'subject_id', 'category', 'nature', 'content', 'scope')
    subjects = await StorySubject.filter(novel_id=commit.novel_id).order_by('id').values('id', 'kind', 'name', 'aliases')
    context = {'source_snapshot': commit.source_snapshot, 'prior_state': state,
        'prior_facts': facts, 'subjects': subjects}
    if commit.replaces_id:
        previous = await get_commit(commit.novel_id, commit.replaces_id)
        context['previous_commit'] = {'id': previous.id, 'source_snapshot': previous.source_snapshot, 'candidate': previous.candidate}
    result = await execution.generate_strict(context)

    async def persist():
        await execution.before_request()
        saved = await save_candidate(commit.novel_id, commit.id, result, params['story_revision'], initial=True)
        return {'commit_id': saved.id, 'status': saved.status, 'revision': saved.revision}

    return await execute_step(params['task_id'], 'persist:story-memory-candidate', persist, atomic=True)
