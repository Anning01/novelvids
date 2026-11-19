"""Read versioned memory and freeze the optional data sent with production requests."""

import json

from fastapi import HTTPException
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.chapter import Chapter
from models.story_memory import StoryCommit, StoryFact, StorySnapshot, StorySubject
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.plan_sources import fingerprint
from services.creation_objects import project_write
from services.story_memory.sources import latest_commit, predecessor
from services.story_memory.status import memory_status

MAX_GENERATION_MEMORY_CHARACTERS = 8000


async def edition_facts(novel_id, commit, snapshot, root, chapter):
    if not snapshot.data['fact_ids']:
        return [], []
    number = chapter.number if chapter else None
    facts = await StoryFact.filter(novel_id=novel_id, id__in=snapshot.data['fact_ids']).order_by('id')
    subject_ids = {fact.subject_id for fact in facts} | {fact.scope.get('world_id') for fact in facts if fact.scope.get('world_id')}
    subjects = {item.id: item for item in await StorySubject.filter(novel_id=novel_id,
        id__in=subject_ids).order_by('id')}
    # Read aliases from this edition's lineage, never the catalog's later alias union.
    lineage = []
    editions = {item.id: item for item in await StoryCommit.filter(novel_id=novel_id,
        status='accepted', id__lte=commit.id).only('id', 'parent_id', 'candidate')}
    cursor = commit
    while cursor is not None:
        lineage.append(cursor)
        cursor = editions[cursor.parent_id] if cursor.parent_id else None
    identities = {(subject.kind, subject.name): subject.id for subject in subjects.values()}
    aliases = {}
    for edition in reversed(lineage):
        for proposal in edition.candidate.get('subjects', []):
            identifier = proposal.get('existing_id') or identities.get((proposal['kind'], proposal['name']))
            if identifier in subjects:
                aliases.setdefault(identifier, set()).update(proposal.get('aliases', []))
    text = chapter.production_text if chapter else ''
    relevant = {subject.id for subject in subjects.values() if any(
        name and name in text for name in [subject.name, *aliases.get(subject.id, [])])}
    baseline_ids = set(root.data['fact_ids'])
    selected = []
    for fact in facts:
        scope = fact.scope
        if number is not None and (scope.get('from_chapter') and number < scope['from_chapter']
                or scope.get('until_chapter') and number > scope['until_chapter']):
            continue
        if (fact.id not in baseline_ids and fact.commit_id != commit.id
                and fact.category not in {'world', 'rule', 'outline'} and fact.subject_id not in relevant):
            continue
        subject = subjects[fact.subject_id]
        selected.append({'id': fact.id, 'commit_id': fact.commit_id,
            'subject': {'id': subject.id, 'kind': subject.kind, 'name': subject.name,
                        'aliases': sorted(aliases.get(subject.id, []))},
            'category': fact.category, 'nature': fact.nature, 'content': fact.content,
            'scope': scope, 'evidence': fact.evidence})
    world_ids = {fact['scope'].get('world_id') for fact in selected} | {
        fact['subject']['id'] for fact in selected if fact['subject']['kind'] == 'world'}
    worlds = [{'id': subject.id, 'name': subject.name} for subject in subjects.values()
              if subject.kind == 'world' and subject.id in world_ids]
    return selected, worlds


async def story_context(novel_id, chapter_id=None, *, purpose='generation', supplemental=False):
    unavailable = {'enabled': False, 'chapter_id': chapter_id, 'purpose': purpose}
    baseline = await latest_commit(novel_id, None)
    if baseline is None:
        return unavailable
    states = await memory_status(novel_id)
    state = states['baseline'] if chapter_id is None else next(
        (item for item in states['chapters'] if item['chapter_id'] == chapter_id), None)
    if state is None:
        raise HTTPException(404, '章节不属于当前作品')
    supplemental = supplemental or (states['automatic'] and state['state'] != 'current')
    if supplemental:
        if states['baseline']['state'] != 'current':
            return unavailable
        commit_id = baseline.id
        if chapter_id is not None:
            commit_id = next((row['commit_id'] for row in reversed(states['chapters'])
                              if row['number'] <= state['number'] and row['state'] == 'current'), baseline.id)
    elif purpose == 'screenplay' and chapter_id is not None:
        commit_id = await predecessor(novel_id, chapter_id)
    else:
        if state['state'] != 'current':
            raise HTTPException(409, '故事记忆缺失或已过期，请先在项目页的故事记忆中复核并确认')
        commit_id = state['commit_id']
    commit = await StoryCommit.get(id=commit_id, novel_id=novel_id)
    snapshot = await StorySnapshot.get(commit_id=commit_id)
    root = snapshot if commit.id == baseline.id else await StorySnapshot.get(commit_id=baseline.id)
    chapter = await Chapter.get(id=chapter_id, novel_id=novel_id) if chapter_id else None
    number = chapter.number if chapter else None
    selected, worlds = await edition_facts(novel_id, commit, snapshot, root, chapter)
    prior = await StorySnapshot.get(commit_id=commit.parent_id) if commit.parent_id else None
    return {'enabled': True, 'chapter_id': chapter_id, 'chapter_number': number, 'purpose': purpose,
        'context_position': 'before_chapter' if (supplemental and commit.chapter_id != chapter_id)
            or (not supplemental and purpose == 'screenplay') else 'through_chapter',
        'baseline_commit_id': baseline.id, 'commit_id': commit.id,
        'baseline_summary': root.data['summary'],
        'worlds': worlds,
        'previous': {key: prior.data.get(key) for key in ('summary', 'ending_state')} if prior else None,
        'current': {key: snapshot.data.get(key) for key in ('summary', 'ending_state', 'unresolved')},
        'facts': selected}


def binding(context):
    return {'chapter_id': context['chapter_id'], 'purpose': context['purpose'],
        'enabled': context['enabled'], 'revision': fingerprint(context),
        **({'commit_id': context['commit_id'], 'baseline_commit_id': context['baseline_commit_id']}
           if context['enabled'] else {})}


async def verify_bindings(params):
    frozen = params.get('story_memory_bindings', {})
    if params.get('task_id'):
        task = await AiTask.get_or_none(id=params['task_id'])
        if task:
            frozen = {**frozen, **task.request_params.get('story_memory_bindings', {})}
    for expected in frozen.values():
        if expected.get('supplemental'):
            continue
        current = await story_context(params['novel_id'], expected['chapter_id'], purpose=expected['purpose'])
        if binding(current) != expected:
            raise HTTPException(409, '故事记忆在生成期间已变化，结果已保留，请重新生成')


async def saved_binding(params):
    task = await AiTask.get_or_none(id=params.get('task_id')) if params.get('task_id') else None
    frozen = task.request_params.get('story_memory_bindings', {}) if task else params.get('story_memory_bindings', {})
    return {key: value for key, value in frozen.items() if value['enabled']}


def fit_context(context, budget):
    def fits(data):
        return len(json.dumps(data, ensure_ascii=False)) <= budget

    if not context['enabled'] or budget <= 0:
        return None
    result = {key: value for key, value in context.items() if key not in {'facts', 'worlds', 'baseline_summary', 'current', 'previous'}}
    result['facts'] = []
    if not fits(result):
        return None
    for key in ('current', 'baseline_summary', 'previous', 'worlds'):
        if context[key] and fits({**result, key: context[key]}):
            result[key] = context[key]
    for fact in sorted(context['facts'], key=lambda fact: fact['commit_id'], reverse=True):
        # Source quotations stay in the memory viewer. The generation call needs the structured facts.
        fact = {key: value for key, value in fact.items() if key != 'evidence'}
        if fits({**result, 'facts': [*result['facts'], fact]}):
            result['facts'].append(fact)
    return result if result['facts'] or 'baseline_summary' in result or 'current' in result else None


async def generation_memory(execution, operation, budget):
    params = execution.params
    chapter_id = params.get('chapter_id')
    if operation not in {'assets', 'storyboard', 'screenplay'} or chapter_id is None:
        return None
    from services.story_memory.automatic import enabled, prepare_for_generation

    task_id, novel_id = params['task_id'], params['novel_id']
    key = f'context:story-memory:{operation}'
    saved = await AgentOperation.get_or_none(task_id=task_id, key=key, state='completed')
    if saved is not None:
        return saved.result['context']
    if budget <= 0:
        return None
    automatic = await enabled(novel_id)
    if not automatic and not await StoryCommit.filter(novel_id=novel_id, chapter_id=None, status='accepted').exists():
        return None
    if await AgentOperation.filter(task_id=task_id, key=f'model:strict:{operation}', state='completed').exists():
        return None
    if automatic:
        await prepare_for_generation(execution, chapter_id)

    async def freeze():
        async with project_write(novel_id):
            context = fit_context(await story_context(novel_id, chapter_id, purpose=operation, supplemental=True), budget)
            if context is not None:
                task = await AiTask.get(id=task_id)
                bindings = {**task.request_params.get('story_memory_bindings', {}),
                    f'{operation}:{chapter_id}': {**binding(context), 'supplemental': True}}
                await AiTask.filter(id=task_id).update(request_params={**task.request_params, 'story_memory_bindings': bindings})
        return {'context': context}

    return (await execute_step(task_id, key, freeze, atomic=True))['context']
