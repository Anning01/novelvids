"""Candidate validation, human decisions and atomic fact publication."""

from datetime import datetime, timezone
from fastapi import HTTPException
from models.story_memory import StoryCommit, StoryFact, StorySnapshot, StorySubject
from schemas.story_memory import StoryCandidate, StoryReview
from services.creation_agent.plan_sources import fingerprint
from services.creation_objects import project_write
from services.story_memory.sources import conflict, parent_state, verify_inputs

EMPTY_BASELINE = '全局故事底稿没有可确认事实，请补充故事材料后重新分析'


def package_hash(commit):
    return fingerprint([commit.id, commit.revision, commit.source_hash, commit.parent_id,
        commit.replaces_id, commit.candidate, commit.review])


async def get_commit(novel_id, commit_id):
    commit = await StoryCommit.get_or_none(id=commit_id, novel_id=novel_id)
    if commit is None:
        raise HTTPException(404, '故事提交不存在')
    return commit


async def validate_candidate(commit, candidate):
    candidate = StoryCandidate.model_validate(candidate)
    for subject in candidate.subjects:
        if subject.existing_id:
            existing = await StorySubject.get_or_none(id=subject.existing_id, novel_id=commit.novel_id)
            if existing is None or existing.kind != subject.kind or existing.name != subject.name:
                raise HTTPException(422, '故事对象标识与当前作品不匹配')
            if not set(existing.aliases) <= set(subject.aliases):
                raise HTTPException(422, '更新对象时须保留已有别名')
        elif await StorySubject.filter(novel_id=commit.novel_id, kind=subject.kind, name=subject.name).exists():
            raise HTTPException(422, '同名故事对象已存在，请核对身份并显式引用 existing_id；不同对象须使用可区分的标准名')
    state = await parent_state(commit)
    active = {fact.id: fact for fact in await StoryFact.filter(novel_id=commit.novel_id, id__in=state['fact_ids'])}
    subjects = {subject.ref: subject for subject in candidate.subjects}
    for fact in candidate.facts:
        for evidence in fact.evidence:
            section, key = evidence.source.split('.')
            text = (commit.source_snapshot.get(section) or {}).get(key, '')
            if text[evidence.start:evidence.end] != evidence.quote or evidence.end > len(text):
                raise HTTPException(422, '事实证据必须逐字匹配本次源文本快照及位置')
        if fact.replaces_id:
            previous = active.get(fact.replaces_id)
            subject = subjects[fact.subject_ref]
            if previous is None or previous.subject_id != subject.existing_id or previous.category != fact.category:
                raise HTTPException(422, '只能替代前置记忆中同一对象、同一类别的有效事实')
    return candidate


async def save_candidate(novel_id, commit_id, candidate, expected_revision, *, initial=False):
    async with project_write(novel_id):
        commit = await get_commit(novel_id, commit_id)
        allowed = {'pending'} if initial else {'draft', 'ready', 'needs_review'}
        if commit.status not in allowed or commit.revision != expected_revision:
            conflict('候选已变化或已结束，请重新读取')
        await verify_inputs(commit)
        parsed = await validate_candidate(commit, candidate)
        commit.candidate = parsed.model_dump(mode='json')
        commit.review = {}
        commit.status = 'draft'
        if not initial:
            commit.revision += 1
        commit.package_hash = package_hash(commit)
        await commit.save(update_fields=['candidate', 'review', 'status', 'revision', 'package_hash', 'updated_at'])
        return commit


async def save_review(novel_id, commit_id, revision, candidate_hash, review, *, task_id=None):
    parsed = StoryReview.model_validate(review)
    async with project_write(novel_id):
        commit = await get_commit(novel_id, commit_id)
        if commit.status not in {'draft', 'ready', 'needs_review'} or commit.revision != revision or fingerprint(commit.candidate) != candidate_hash:
            conflict('审核期间候选已变化，本次审核不能使用')
        await verify_inputs(commit)
        await validate_candidate(commit, commit.candidate)
        if any(issue.fact_index is not None and issue.fact_index >= len(commit.candidate['facts']) for issue in parsed.issues):
            raise HTTPException(422, '审核引用了不存在的候选事实')
        commit.review = parsed.model_dump(mode='json')
        if commit.chapter_id is None and not commit.candidate['facts'] and not any(issue.severity == 'blocking' for issue in parsed.issues):
            commit.review['issues'].append({'severity': 'blocking', 'fact_index': None, 'reason': EMPTY_BASELINE})
        if task_id:
            commit.review['task_id'] = str(task_id)
        commit.status = 'needs_review' if any(issue['severity'] == 'blocking' for issue in commit.review['issues']) else 'ready'
        commit.package_hash = package_hash(commit)
        await commit.save(update_fields=['review', 'status', 'package_hash', 'updated_at'])
        return commit


async def save_repaired_candidate(novel_id, commit_id, expected_hash, candidate, review, *, task_id):
    async with project_write(novel_id):
        current = await get_commit(novel_id, commit_id)
        if current.status != 'needs_review' or current.package_hash != expected_hash:
            conflict('候选或审核已变化，补全结果不能使用')
        revised = await save_candidate(novel_id, commit_id, candidate, current.revision)
        return await save_review(novel_id, commit_id, revised.revision, fingerprint(revised.candidate), review, task_id=task_id)


async def decide(novel_id, commit_id, body, actor_id):
    async with project_write(novel_id):
        commit = await get_commit(novel_id, commit_id)
        if commit.package_hash != body.expected_package_hash:
            conflict('确认对应的候选或审核已变化，请重新核对')
        desired = 'accepted' if body.decision == 'accept' else 'rejected'
        if commit.status in {'accepted', 'rejected'}:
            if commit.status != desired:
                conflict('此提交已经结束，不能更改裁决')
            return commit
        if body.decision == 'accept':
            if commit.chapter_id is None and commit.candidate and not commit.candidate.get('facts'):
                conflict(EMPTY_BASELINE)
            if commit.status == 'stale':
                await verify_inputs(commit)
            if commit.status != 'ready' or not commit.review:
                conflict('候选须先完成审核，并处理阻断问题')
            await verify_inputs(commit)
            candidate = await validate_candidate(commit, commit.candidate)
            await publish(commit, candidate)
            if commit.replaces_id:
                from services.story_memory.invalidation import invalidate
                chapter = commit.source_snapshot.get('chapter')
                await invalidate(novel_id, chapter_id=commit.chapter_id,
                    from_number=chapter['number'] + 1 if chapter else None,
                    reason='upstream_commit_changed', exclude_commit_id=commit.id)
        elif commit.status not in {'draft', 'ready', 'needs_review'}:
            conflict('候选尚未生成，不能裁决')
        commit.status = desired
        commit.decided_by, commit.decision = actor_id, body.note
        commit.decided_at = datetime.now(timezone.utc)
        await commit.save(update_fields=['status', 'decided_by', 'decision', 'decided_at', 'updated_at'])
        return commit


async def publish(commit, candidate):
    """Called only under the project's decision transaction; no external side effects."""
    identities = {}
    for item in candidate.subjects:
        if item.existing_id:
            subject = await StorySubject.get(id=item.existing_id, novel_id=commit.novel_id)
        else:
            subject, _ = await StorySubject.get_or_create(novel_id=commit.novel_id, kind=item.kind, name=item.name)
        # Identity is stable; confirmed historical facts retain their original names and evidence.
        subject.aliases = sorted(set(subject.aliases) | set(item.aliases))
        await subject.save(update_fields=['aliases', 'updated_at'])
        identities[item.ref] = subject.id
    inherited = await parent_state(commit)
    active = set(inherited['fact_ids'])
    for item in candidate.facts:
        scope = item.scope.model_dump(mode='json', exclude={'world_ref'})
        scope['world_id'] = identities.get(item.scope.world_ref)
        scope['revealed_in_chapter'] = (commit.source_snapshot.get('chapter') or {}).get('number')
        fact = await StoryFact.create(novel_id=commit.novel_id, commit=commit,
            subject_id=identities[item.subject_ref], category=item.category, nature=item.nature,
            content=item.content, scope=scope, evidence=[e.model_dump() for e in item.evidence],
            replaces_id=item.replaces_id, operation=item.operation)
        if item.replaces_id:
            active.discard(item.replaces_id)
        if item.operation != 'retract':
            active.add(fact.id)
    await StorySnapshot.create(novel_id=commit.novel_id, commit=commit, data={
        'fact_ids': sorted(active), 'summary': candidate.summary,
        'ending_state': candidate.ending_state, 'unresolved': candidate.unresolved})


async def commit_data(commit, *, detail=True):
    reason = None
    try:
        await verify_inputs(commit, check_target=commit.status != 'accepted')
        current = True
        if commit.status == 'accepted':
            from services.story_memory.sources import latest_commit
            latest = await latest_commit(commit.novel_id, commit.chapter_id)
            current = latest.id == commit.id
            if not current:
                reason = '已有更新的正式提交'
    except HTTPException as error:
        if error.status_code not in {404, 409, 422}:
            raise
        current = False
        reason = str(error.detail)
    fields = ('id', 'novel_id', 'chapter_id', 'parent_id', 'replaces_id', 'status', 'revision',
        'source_hash', 'package_hash', 'created_by', 'decided_by', 'decision', 'created_at', 'decided_at')
    data = {key: getattr(commit, key) for key in fields}
    data.update(current=current, stale_reason=reason, request_id=str(commit.request_id), task_id=str(commit.task_id) if commit.task_id else None)
    if detail:
        from models.ai_task import AiTask
        task = await AiTask.get_or_none(id=commit.task_id) if commit.task_id else None
        snapshot = await StorySnapshot.get_or_none(commit_id=commit.id)
        data.update(candidate=commit.candidate, review=commit.review, source_snapshot=commit.source_snapshot,
            snapshot=snapshot.data if snapshot else None,
            recheck_task_id=task.request_params.get('story_recheck_id') if task else None)
        replaced = [fact['replaces_id'] for fact in commit.candidate.get('facts', []) if fact.get('replaces_id')]
        data['replaced_facts'] = {row['id']: row['content'] for row in await StoryFact.filter(
            novel_id=commit.novel_id, id__in=replaced).values('id', 'content')}
    return data
