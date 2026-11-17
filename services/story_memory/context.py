"""One temporal story context for production, editors and conversation tools."""

from fastapi import HTTPException
from models.ai_task import AiTask
from models.chapter import Chapter
from models.story_memory import StoryCommit, StoryFact, StorySnapshot, StorySubject
from services.creation_agent.plan_sources import fingerprint
from services.creation_objects import project_write
from services.story_memory.sources import latest_commit, predecessor
from services.story_memory.status import memory_status


async def story_context(novel_id, chapter_id=None, *, purpose='generation'):
    baseline = await latest_commit(novel_id, None)
    if baseline is None:
        return {'enabled': False, 'chapter_id': chapter_id, 'purpose': purpose}
    states = await memory_status(novel_id)
    state = states['baseline'] if chapter_id is None else next(
        (item for item in states['chapters'] if item['chapter_id'] == chapter_id), None)
    if state is None:
        raise HTTPException(404, '章节不属于当前作品')
    if purpose == 'screenplay' and chapter_id is not None:
        commit_id = await predecessor(novel_id, chapter_id)
    else:
        if state['state'] != 'current':
            raise HTTPException(409, '故事记忆缺失或已过期，请先在项目页的故事记忆中复核并确认')
        commit_id = state['commit_id']
    commit = await StoryCommit.get(id=commit_id, novel_id=novel_id)
    snapshot = await StorySnapshot.get(commit_id=commit_id)
    root = await StorySnapshot.get(commit_id=baseline.id)
    chapter = await Chapter.get(id=chapter_id, novel_id=novel_id) if chapter_id else None
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
    prior = await StorySnapshot.get(commit_id=commit.parent_id) if commit.parent_id else None
    world_ids = {fact['scope'].get('world_id') for fact in selected} | {
        fact['subject']['id'] for fact in selected if fact['subject']['kind'] == 'world'}
    return {'enabled': True, 'chapter_id': chapter_id, 'chapter_number': number, 'purpose': purpose,
        'context_position': 'before_chapter' if purpose == 'screenplay' else 'through_chapter',
        'baseline_commit_id': baseline.id, 'commit_id': commit.id,
        'baseline_summary': root.data['summary'],
        'worlds': [{'id': subject.id, 'name': subject.name} for subject in subjects.values()
                   if subject.kind == 'world' and subject.id in world_ids],
        'previous': {key: prior.data.get(key) for key in ('summary', 'ending_state')} if prior else None,
        'current': {key: snapshot.data.get(key) for key in ('summary', 'ending_state', 'unresolved')},
        'facts': selected}


def binding(context):
    return {'chapter_id': context['chapter_id'], 'purpose': context['purpose'],
        'enabled': context['enabled'], 'revision': fingerprint(context),
        **({'commit_id': context['commit_id'], 'baseline_commit_id': context['baseline_commit_id']}
           if context['enabled'] else {})}


async def capture_binding(novel_id, chapter_id, purpose):
    context = await story_context(novel_id, chapter_id, purpose=purpose)
    return {f'{purpose}:{chapter_id}': binding(context)}


async def execution_context(execution, chapter_id=None, *, purpose='generation', model_key=None):
    params = execution.params
    novel_id = params['novel_id']
    chapter_id = chapter_id if chapter_id is not None else params.get('chapter_id')
    async with project_write(novel_id):
        context = await story_context(novel_id, chapter_id, purpose=purpose)
        key, current = f'{purpose}:{chapter_id}', binding(context)
        task = await AiTask.get(id=params['task_id'])
        frozen = {**params.get('story_memory_bindings', {}), **task.request_params.get('story_memory_bindings', {})}
        if model_key and context['enabled'] and key not in frozen:
            from models.agent_operation import AgentOperation
            if await AgentOperation.filter(task=task, key=model_key, state='completed').exists():
                raise HTTPException(409, '旧生成结果未绑定故事记忆，请重新生成；原有结果仍保留')
        if key in frozen and frozen[key] != current:
            raise HTTPException(409, '故事记忆在任务提交后已变化，请重新生成；已有结果仍保留')
        frozen[key] = current
        params['story_memory_bindings'] = frozen
        await AiTask.filter(id=task.id).update(request_params={**task.request_params, 'story_memory_bindings': frozen})
    return context


async def verify_bindings(params):
    frozen = params.get('story_memory_bindings', {})
    if params.get('task_id'):
        task = await AiTask.get_or_none(id=params['task_id'])
        if task:
            frozen = {**frozen, **task.request_params.get('story_memory_bindings', {})}
    for expected in frozen.values():
        current = await story_context(params['novel_id'], expected['chapter_id'], purpose=expected['purpose'])
        if binding(current) != expected:
            raise HTTPException(409, '故事记忆在生成期间已变化，结果已保留，请复核后重新生成')


async def saved_binding(params):
    task = await AiTask.get_or_none(id=params.get('task_id')) if params.get('task_id') else None
    frozen = task.request_params.get('story_memory_bindings', {}) if task else params.get('story_memory_bindings', {})
    return {key: value for key, value in frozen.items() if value['enabled']}


async def conversation_memory(novel_id, chapter_id=None):
    try:
        context = await story_context(novel_id, chapter_id)
    except HTTPException as error:
        if error.status_code != 409:
            raise
        return {'enabled': True, 'state': 'needs_review', 'message': str(error.detail)}
    if not context['enabled']:
        return context
    return {**context, 'facts': context['facts'][:3], 'fact_count': len(context['facts']),
        'has_more': len(context['facts']) > 3, 'revision': fingerprint(context)}


async def add_generation_context(execution, facts):
    operation = execution.params['output_contract']['name']
    model_key = 'model:strict:' + operation
    if operation in {'assets', 'storyboard', 'screenplay'}:
        context = await execution_context(execution, purpose=operation, model_key=model_key)
        return {**facts, 'story_memory': context} if context['enabled'] else facts
    if operation.startswith('scene_prompt_edit'):
        from models.scene import Scene
        targets = facts.get('targets') or [facts.get('target', {})]
        scenes = await Scene.filter(id__in=[target['id'] for target in targets if target.get('id')],
            chapter__novel_id=execution.params['novel_id']).order_by('id')
        contexts = []
        for chapter_id in dict.fromkeys(scene.chapter_id for scene in scenes):
            context = await execution_context(execution, chapter_id, purpose='storyboard', model_key=model_key)
            if context['enabled']:
                contexts.append({**context, 'applies_to': [scene.id for scene in scenes if scene.chapter_id == chapter_id]})
        if contexts:
            return {**facts, 'story_memory': {'enabled': True, 'contexts': contexts}}
    return facts
