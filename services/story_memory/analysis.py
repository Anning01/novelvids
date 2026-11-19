"""Extract one strict candidate and save it for confirmation."""

from models.story_memory import StoryFact, StorySnapshot, StorySubject
from schemas.story_memory import StoryDecision, StoryMemoryNote
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.strict_text import require_text_execution
from services.story_memory.sources import conflict, latest_commit, parent_state, verify_inputs
from services.story_memory.store import decide, get_commit, save_candidate


async def note_context(commit):
    source = commit.source_snapshot
    if commit.chapter_id is None:
        return {'source_snapshot': source}

    baseline = await latest_commit(commit.novel_id, None)
    root = await StorySnapshot.get(commit_id=baseline.id)
    context = {'source_snapshot': {key: value for key, value in source.items()
                                   if key in {'chapter', 'preceding_excerpt'}},
               'baseline_summary': root.data['summary']}
    if commit.parent_id != baseline.id:
        previous = await StorySnapshot.get(commit_id=commit.parent_id)
        context['previous'] = {key: previous.data[key] for key in ('summary', 'ending_state')
                               if previous.data.get(key)}
    return context


async def legacy_context(commit):
    """Version-one tasks already queued have a frozen extraction contract."""
    state = await parent_state(commit)
    facts = await StoryFact.filter(novel_id=commit.novel_id, id__in=state['fact_ids']).order_by('id').values(
        'id', 'subject_id', 'category', 'nature', 'content', 'scope')
    subjects = await StorySubject.filter(novel_id=commit.novel_id).order_by('id').values('id', 'kind', 'name', 'aliases')
    context = {'source_snapshot': commit.source_snapshot, 'prior_state': state,
        'prior_facts': facts, 'subjects': subjects}
    if commit.replaces_id:
        previous = await get_commit(commit.novel_id, commit.replaces_id)
        context['previous_commit'] = {'id': previous.id, 'source_snapshot': previous.source_snapshot, 'candidate': previous.candidate}
    return context


async def analyze(params):
    if params['operation'] != 'story_memory_analyze':
        conflict('候选可以直接确认入库')
    execution = require_text_execution(params)
    commit = await get_commit(params['novel_id'], params['story_commit_id'])
    await verify_inputs(commit)
    if commit.revision != params['story_revision']:
        conflict('候选版本已变化，请重新读取')
    legacy = params['output_contract']['version'] == 1
    context = await legacy_context(commit) if legacy else await note_context(commit)
    result = await execution.generate_strict(context)

    if not legacy:
        note = StoryMemoryNote.model_validate(result)
        result = {'summary': note.summary, 'ending_state': '', 'subjects': [], 'facts': [], 'unresolved': []}

    async def persist():
        await execution.before_request()
        saved = await save_candidate(commit.novel_id, commit.id, result, params['story_revision'], initial=True)
        if params.get('automatic_story_memory'):
            saved = await decide(commit.novel_id, commit.id, StoryDecision(
                decision='accept', expected_package_hash=saved.package_hash), None)
        return {'commit_id': saved.id, 'status': saved.status, 'revision': saved.revision}

    return await execute_step(params['task_id'], 'persist:story-memory-candidate', persist, atomic=True)
