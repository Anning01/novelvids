import asyncio
from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from auth.deps import AuthContext
from controllers.story_memory import submit_analysis, submit_review
from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.story_memory import StoryCommit, StoryFact, StorySnapshot, StorySubject
from schemas.story_memory import StoryAnalysisRequest, StoryCandidate, StoryDecision, StoryReviewRequest
from services.creation_agent.plan_sources import fingerprint
from services.story_memory.sources import latest_commit, predecessor, source_snapshot
from services.story_memory.store import commit_data, decide, save_candidate, save_review


@pytest.fixture(autouse=True)
def local_workspace(monkeypatch):
    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)


@pytest.fixture
async def project():
    return await Novel.create(name='故城', project_setting='古代王朝，没有电力。', story_outline='邻居守护城门。')


def candidate(text='古代王朝，没有电力。', *, source='project.setting', existing_id=None, content='古代王朝没有电力。'):
    return {'subjects': [{'ref': 'world', 'existing_id': existing_id, 'kind': 'world', 'name': '故城世界', 'aliases': []}],
        'facts': [{'subject_ref': 'world', 'category': 'world', 'nature': 'fact', 'content': content,
            'scope': {'world_ref': 'world', 'scene': None, 'from_chapter': None, 'until_chapter': None, 'story_time': None},
            'evidence': [{'source': source, 'start': 0, 'end': len(text), 'quote': text}],
            'operation': 'add', 'replaces_id': None}],
        'summary': content, 'ending_state': '', 'unresolved': []}


async def pending(project, chapter=None):
    source = await source_snapshot(project.id, chapter.id if chapter else None)
    previous = await latest_commit(project.id, chapter.id if chapter else None)
    return await StoryCommit.create(novel=project, chapter=chapter, request_id=uuid4(),
        source_snapshot=source, source_hash=fingerprint(source),
        parent_id=await predecessor(project.id, chapter.id if chapter else None),
        replaces_id=previous.id if previous else None)


async def reviewed(project, chapter=None, payload=None, issues=None):
    row = await pending(project, chapter)
    subject = await StorySubject.get_or_none(novel=project, name='故城世界')
    row = await save_candidate(project.id, row.id, payload or candidate(existing_id=subject.id if subject else None), 1, initial=True)
    return await save_review(project.id, row.id, row.revision, fingerprint(row.candidate),
        {'issues': issues or [], 'summary': '逐项核对了主体、时点和原文依据。'})


async def accept(project, row, actor=17):
    return await decide(project.id, row.id, StoryDecision(expected_package_hash=row.package_hash,
        decision='accept', note='确认本次候选。'), actor)


@pytest.mark.asyncio
async def test_candidate_review_confirmation_and_history_preserve_existing_data(project):
    chapter = await Chapter.create(novel=project, number=1, name='邻居', content='原文', screenplay='邻居守着木门。')
    asset = await Asset.create(novel=project, canonical_name='已有邻居', asset_type=1, base_traits='用户已保存的设计')
    row = await pending(project)
    row = await save_candidate(project.id, row.id, candidate(), 1, initial=True)
    assert row.status == 'draft'
    assert not await StoryFact.all().exists() and not await StorySubject.all().exists()
    with pytest.raises(HTTPException, match='审核'):
        await accept(project, row)
    row = await save_review(project.id, row.id, row.revision, fingerprint(row.candidate), {'issues': [], 'summary': '核对通过'})
    assert not await StoryFact.all().exists()
    row = await accept(project, row)
    assert row.status == 'accepted' and row.decided_by == 17
    assert await StoryFact.all().count() == await StorySubject.all().count() == await StorySnapshot.all().count() == 1
    detail = await commit_data(row)
    assert detail['current'] and detail['source_snapshot']['project']['setting'] == project.project_setting
    assert detail['snapshot']['fact_ids'] == [await StoryFact.all().first().values_list('id', flat=True)]
    await project.refresh_from_db()
    await chapter.refresh_from_db()
    await asset.refresh_from_db()
    assert project.story_outline == '邻居守护城门。' and project.project_setting == '古代王朝，没有电力。'
    assert chapter.screenplay == '邻居守着木门。' and asset.base_traits == '用户已保存的设计'


@pytest.mark.asyncio
async def test_repeated_and_parallel_decisions_publish_once(project):
    row = await reviewed(project)
    first, second = await asyncio.gather(accept(project, row), accept(project, row))
    assert first.id == second.id
    assert await StoryFact.all().count() == await StorySnapshot.all().count() == 1
    with pytest.raises(HTTPException, match='结束'):
        await decide(project.id, row.id, StoryDecision(expected_package_hash=row.package_hash, decision='reject'), 17)


@pytest.mark.asyncio
async def test_blocking_review_rejection_and_candidate_edit_invalidate_approval(project):
    row = await reviewed(project, issues=[{'severity': 'blocking', 'fact_index': 0, 'reason': '证言被写成了事实'}])
    assert row.status == 'needs_review'
    with pytest.raises(HTTPException, match='阻断'):
        await accept(project, row)
    old_hash = row.package_hash
    updated = await save_candidate(project.id, row.id, candidate(content='仅作为候选核对'), row.revision)
    assert updated.revision == 2 and updated.status == 'draft' and not updated.review
    with pytest.raises(HTTPException, match='变化'):
        await accept(project, row)
    with pytest.raises(HTTPException, match='审核期间'):
        await save_review(project.id, row.id, 1, fingerprint(row.candidate), {'issues': [], 'summary': '迟到审核'})
    with pytest.raises(HTTPException, match='变化'):
        await save_candidate(project.id, row.id, candidate(), 1)
    rejected = await decide(project.id, row.id, StoryDecision(expected_package_hash=updated.package_hash,
        decision='reject', note='退回修改'), 23)
    assert rejected.status == 'rejected' and rejected.decided_by == 23
    assert old_hash != rejected.package_hash and not await StoryFact.all().exists()


@pytest.mark.asyncio
async def test_rereview_blocks_unresolved_conflicts_and_revokes_prior_approval_package(project):
    payload = candidate()
    payload['facts'][0]['nature'] = 'inference'
    payload['unresolved'] = ['前后章首次停电的时序互斥，尚未修正剧本。']
    row = await reviewed(project, payload=payload)
    previously_ready_hash = row.package_hash
    row = await save_review(project.id, row.id, row.revision, fingerprint(row.candidate), {
        'issues': [{'severity': 'blocking', 'fact_index': 0, 'reason': '标注待确认不能解除未解决的时序矛盾。'}],
        'summary': '须修正剧本或候选并重新审核。'})
    assert row.status == 'needs_review'
    with pytest.raises(HTTPException, match='变化'):
        await decide(project.id, row.id, StoryDecision(expected_package_hash=previously_ready_hash,
            decision='accept'), 17)
    with pytest.raises(HTTPException, match='阻断'):
        await accept(project, row)
    assert not await StoryFact.all().exists() and not await StorySnapshot.all().exists()


@pytest.mark.asyncio
async def test_changed_source_rejects_approval_and_retains_snapshot(project):
    row = await reviewed(project)
    project.project_setting = '未来世界，有电力。'
    await project.save(update_fields=['project_setting'])
    with pytest.raises(HTTPException, match='变化'):
        await accept(project, row)
    assert not await StoryFact.all().exists()
    detail = await commit_data(await StoryCommit.get(id=row.id))
    assert not detail['current'] and detail['source_snapshot']['project']['setting'] == '古代王朝，没有电力。'


@pytest.mark.asyncio
async def test_evidence_scope_subject_and_cross_project_validation(project):
    row = await pending(project)
    other = await Novel.create(name='另一部书')
    foreign = await StorySubject.create(novel=other, kind='world', name='故城世界')
    bad_quote = candidate()
    bad_quote['facts'][0]['evidence'][0]['quote'] = '原文没有这句话'
    bad_range = candidate()
    bad_range['facts'][0]['evidence'][0].update(start=1, end=200)
    for payload in (bad_quote, bad_range, candidate(existing_id=foreign.id)):
        with pytest.raises(HTTPException) as error:
            await save_candidate(project.id, row.id, payload, 1, initial=True)
        assert error.value.status_code == 422
    assert (await StoryCommit.get(id=row.id)).status == 'pending'
    invalid = candidate()
    invalid['facts'][0]['scope']['world_ref'] = 'missing'
    with pytest.raises(ValidationError):
        StoryCandidate.model_validate(invalid)


@pytest.mark.asyncio
async def test_baseline_and_chapter_prefix_are_required_and_versioned(project):
    first = await Chapter.create(novel=project, number=1, name='第一章', content='原文', screenplay='古城断水。')
    second = await Chapter.create(novel=project, number=2, name='第二章', content='守卫离开。')
    with pytest.raises(HTTPException, match='全局'):
        await pending(project, first)
    baseline = await accept(project, await reviewed(project))
    with pytest.raises(HTTPException, match='第 1 章'):
        await pending(project, second)
    subject = await StorySubject.get(novel=project)
    one = await accept(project, await reviewed(project, first, candidate(first.screenplay, source='chapter.text', existing_id=subject.id)))
    two = await reviewed(project, second, candidate(second.content, source='chapter.text', existing_id=subject.id))
    assert one.parent_id == baseline.id and two.parent_id == one.id
    assert one.source_snapshot['chapter']['kind'] == 'screenplay'
    assert two.source_snapshot['chapter']['kind'] == 'source'
    first.screenplay = '古城恢复供水。'
    await first.save(update_fields=['screenplay'])
    with pytest.raises(HTTPException, match='第 1 章'):
        await accept(project, two)
    assert not (await commit_data(one))['current']


@pytest.mark.asyncio
async def test_new_baseline_or_competing_commit_invalidates_old_candidates(project):
    a, b = await reviewed(project), await reviewed(project)
    await accept(project, a)
    with pytest.raises(HTTPException, match='新的正式提交'):
        await accept(project, b)
    new = await accept(project, await reviewed(project))
    assert new.replaces_id == a.id and not (await commit_data(a))['current']
    assert (await commit_data(new))['current']


@pytest.mark.asyncio
async def test_replacements_retractions_and_rollback_are_atomic(project, monkeypatch):
    baseline = await accept(project, await reviewed(project))
    old_fact = await StoryFact.get(commit=baseline)
    subject = await StorySubject.get(id=old_fact.subject_id)
    first = await Chapter.create(novel=project, number=1, name='变化', content='古城出现电力。')
    payload = candidate(first.content, source='chapter.text', existing_id=subject.id)
    payload['facts'][0].update(operation='replace', replaces_id=old_fact.id, content=first.content)
    row = await reviewed(project, first, payload)
    original = StorySnapshot.create
    monkeypatch.setattr(StorySnapshot, 'create', AsyncMock(side_effect=RuntimeError('snapshot failure')))
    with pytest.raises(RuntimeError):
        await accept(project, row)
    assert await StoryFact.all().count() == 1
    assert (await StoryCommit.get(id=row.id)).status == 'ready'
    monkeypatch.setattr(StorySnapshot, 'create', original)
    await accept(project, row)
    new_fact = await StoryFact.get(commit=row)
    assert (await StorySnapshot.get(commit=row)).data['fact_ids'] == [new_fact.id]
    assert (await StorySnapshot.get(commit=baseline)).data['fact_ids'] == [old_fact.id]
    second = await Chapter.create(novel=project, number=2, name='纠正', content='前次电光并非电力。')
    payload = candidate(second.content, source='chapter.text', existing_id=subject.id)
    payload['facts'][0].update(operation='retract', replaces_id=new_fact.id)
    retracted = await accept(project, await reviewed(project, second, payload))
    assert (await StorySnapshot.get(commit=retracted)).data['fact_ids'] == []
    assert await StoryFact.all().count() == 3  # Original and retraction evidence remain immutable.


@pytest.mark.asyncio
async def test_analysis_task_is_idempotent_and_review_is_a_separate_call(project, monkeypatch):
    from models.config import AiModelConfig
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    await AiModelConfig.create(name='strict', model='strict', task_type=7,
        base_url='https://model.invalid', api_key='test', supports_strict_output=True, is_active=True)
    seen = []
    async def generate(self, facts):
        seen.append((self.params['output_contract']['name'], facts))
        if len(seen) == 1:
            payload = candidate()
            payload['facts'][0]['evidence'][0]['end'] -= 1
            return payload
        return {'issues': [], 'summary': '原文依据核对通过'}
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)
    request = StoryAnalysisRequest(request_id=uuid4())
    task = await submit_analysis(project.id, request, AuthContext())
    assert (await submit_analysis(project.id, request, AuthContext())).id == task.id
    assert 'api_key' not in task.request_params and task.request_params['operation'] == 'story_memory_analyze'
    with pytest.raises(HTTPException, match='同一请求'):
        await submit_analysis(project.id, request.model_copy(update={'skill_id': 0}), AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    row = await StoryCommit.get(task=task)
    assert row.status == 'ready' and not await StoryFact.all().exists()
    assert row.review['task_id'] == str(task.id)
    assert [name for name, _ in seen] == ['story_memory_extract', 'story_memory_review']
    assert 'candidate' in seen[1][1] and seen[0][1]['source_snapshot']['project']['setting'] == project.project_setting
    assert seen[1][1]['candidate']['facts'][0]['evidence'][0]['end'] == len(project.project_setting)
    updated = await save_candidate(project.id, row.id, candidate(), row.revision)
    review_task = await submit_review(project.id, row.id, StoryReviewRequest(expected_revision=updated.revision), AuthContext())
    assert (await submit_review(project.id, row.id, StoryReviewRequest(expected_revision=updated.revision), AuthContext())).id == review_task.id
    await ai_task_executor.run(review_task)
    await review_task.refresh_from_db()
    assert review_task.status == 3, review_task.error_message


@pytest.mark.asyncio
async def test_review_failure_keeps_editable_candidate_and_never_publishes(project, monkeypatch):
    from models.config import AiModelConfig
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    await AiModelConfig.create(name='strict', model='strict', task_type=7,
        base_url='https://model.invalid', api_key='test', supports_strict_output=True, is_active=True)
    async def generate(self, facts):
        if self.params['output_contract']['name'].endswith('review'):
            raise RuntimeError('review unavailable')
        return candidate()
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)
    task = await submit_analysis(project.id, StoryAnalysisRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    row = await StoryCommit.get(task=task)
    assert task.status == 4 and row.status == 'draft'
    assert row.candidate['facts'] and not await StoryFact.all().exists()


@pytest.mark.asyncio
async def test_reanalysis_excludes_host_review_receipts_from_model_context(project, monkeypatch):
    from models.config import AiModelConfig
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    previous = await reviewed(project)
    previous = await save_review(project.id, previous.id, previous.revision, fingerprint(previous.candidate),
        {'issues': [], 'summary': '已核对'}, task_id=uuid4())
    previous = await accept(project, previous)
    subject = await StorySubject.get(novel=project)
    await AiModelConfig.create(name='strict', model='strict', task_type=7,
        base_url='https://model.invalid', api_key='test', supports_strict_output=True, is_active=True)
    contexts = []
    async def generate(self, context):
        contexts.append(context)
        return (candidate(existing_id=subject.id) if self.params['operation'] == 'story_memory_analyze'
            and self.params['output_contract']['name'].endswith('extract') else {'issues': [], 'summary': '已核对'})
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)
    task = await submit_analysis(project.id, StoryAnalysisRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(contexts) == 2
    assert all(context['previous_commit']['review'] == {'issues': [], 'summary': '已核对'} for context in contexts)
    assert (await StoryCommit.get(id=previous.id)).review['task_id'] == previous.review['task_id']


def test_prompt_language_and_strict_contracts():
    from prompts.story_memory import contract, method
    from prompts.text_tasks import render_text_task
    for language in ('zh', 'en'):
        for stage in ('extract', 'review'):
            system, content = render_text_task(language=language,
                skill=method({'instructions': '自定义方法', 'references': []}, stage, language), context={})
            assert f'language={language}' in system + content
            assert ('不能登记为已发生事件' if stage == 'extract' else '不代用户批准') in content
            if stage == 'extract':
                assert 'facts.subject_ref 或 scope.world_ref 实际引用的对象' in content
                assert '各场景的事实填写对应 scope.world_ref' in content
                assert '不把同一世界的断电、灾变等状态变化另建成新世界' in content
            else:
                assert '场景世界范围或混淆回忆与当前世界时，标为 blocking' in content
                assert '与前置正式记忆在同一对象的事实时序或规则上不可同时成立' in content
                assert '把互斥事实写进 unresolved、标成 inference、并列两说或声明留待用户裁决，都不能解除阻断' in content
            schema = contract(stage)
            assert schema['name'] == f'story_memory_{stage}'
            def check(value):
                if isinstance(value, dict):
                    assert 'default' not in value
                    if value.get('type') == 'object':
                        assert set(value['required']) == set(value['properties']) and value['additionalProperties'] is False
                    for item in value.values():
                        check(item)
                if isinstance(value, list):
                    for item in value:
                        check(item)
            check(schema['schema'])


@pytest.mark.parametrize('mutation', ['unknown', 'duplicate', 'replacement', 'range', 'unused_subject'])
def test_candidate_contract_rejects_ambiguous_changes(mutation):
    payload = deepcopy(candidate())
    if mutation == 'unknown':
        payload['facts'][0]['subject_ref'] = 'unknown'
    elif mutation == 'duplicate':
        payload['subjects'].append(deepcopy(payload['subjects'][0]))
    elif mutation == 'replacement':
        payload['facts'][0]['operation'] = 'replace'
    elif mutation == 'unused_subject':
        payload['subjects'].append({'ref': 'city', 'kind': 'location', 'name': '故城'})
    else:
        payload['facts'][0]['scope'].update(from_chapter=3, until_chapter=1)
    with pytest.raises(ValidationError):
        StoryCandidate.model_validate(payload)


@pytest.mark.asyncio
async def test_exact_evidence_keeps_whitespace_and_unicode(project):
    project.project_setting = '\n  古城🏯，没有电力。\n'
    await project.save(update_fields=['project_setting'])
    row = await reviewed(project, payload=candidate(project.project_setting))
    row = await accept(project, row)
    fact = await StoryFact.get(commit=row)
    assert fact.evidence[0]['quote'] == project.project_setting


@pytest.mark.asyncio
async def test_model_evidence_anchors_unique_quotes_without_weakening_store_validation(project):
    from services.story_memory.evidence import anchor_evidence
    project.project_setting = '前文🏯。周砚停在门前，没有穿过去。\n后文。'
    await project.save(update_fields=['project_setting'])
    row = await pending(project)
    quote = '周砚停在门前，没有穿过去。'
    payload = candidate(quote)
    payload['facts'][0]['evidence'][0].update(start=4, end=16)
    anchored = anchor_evidence(payload, row.source_snapshot)
    assert anchored['facts'][0]['evidence'][0] == {'source': 'project.setting',
        'quote': quote, 'start': 4, 'end': 4 + len(quote)}
    assert payload['facts'][0]['evidence'][0]['end'] == 16
    with pytest.raises(HTTPException, match='逐字匹配'):
        await save_candidate(project.id, row.id, payload, 1, initial=True)
    await save_candidate(project.id, row.id, anchored, 1, initial=True)


@pytest.mark.parametrize('text,quote,start,end,expected', [
    ('古城。古城。', '古城', 1, 3, (1, 3)),
    ('古城。古城。', '古城', 3, 5, (3, 5)),
    ('古城。', '未来城', 0, 3, (0, 3)),
    ('\n  古城🏯。\n', '  古城🏯。', 0, 5, (1, 7)),
])
def test_evidence_anchor_preserves_ambiguous_missing_and_exact_quotes(text, quote, start, end, expected):
    from services.story_memory.evidence import anchor_evidence
    payload = candidate(quote)
    payload['facts'][0]['evidence'][0].update(start=start, end=end)
    result = anchor_evidence(payload, {'project': {'setting': text}})
    evidence = result['facts'][0]['evidence'][0]
    assert (evidence['start'], evidence['end']) == expected and evidence['quote'] == quote


@pytest.mark.asyncio
async def test_same_name_requires_explicit_identity_and_old_aliases_are_preserved(project):
    await accept(project, await reviewed(project))
    subject = await StorySubject.get(novel=project)
    subject.aliases = ['旧称']
    await subject.save(update_fields=['aliases'])
    row = await pending(project)
    for payload in (candidate(), candidate(existing_id=subject.id)):
        with pytest.raises(HTTPException) as error:
            await save_candidate(project.id, row.id, payload, 1, initial=True)
        assert error.value.status_code == 422
    payload = candidate(existing_id=subject.id)
    payload['subjects'][0]['aliases'] = ['旧称', '新称']
    saved = await save_candidate(project.id, row.id, payload, 1, initial=True)
    assert saved.status == 'draft'
    await subject.refresh_from_db()
    assert subject.aliases == ['旧称']  # A candidate cannot change the official identity catalog.


@pytest.mark.asyncio
async def test_invented_replacement_and_invalid_review_reference_are_rejected(project):
    baseline = await accept(project, await reviewed(project))
    subject = await StorySubject.get(novel=project)
    chapter = await Chapter.create(novel=project, number=1, name='一', content='古城断水。')
    row = await pending(project, chapter)
    payload = candidate(chapter.content, source='chapter.text', existing_id=subject.id)
    payload['facts'][0].update(operation='replace', replaces_id=999999)
    with pytest.raises(HTTPException, match='有效事实'):
        await save_candidate(project.id, row.id, payload, 1, initial=True)
    payload['facts'][0].update(operation='add', replaces_id=None)
    saved = await save_candidate(project.id, row.id, payload, 1, initial=True)
    with pytest.raises(HTTPException, match='不存在'):
        await save_review(project.id, saved.id, 1, fingerprint(saved.candidate), {
            'issues': [{'severity': 'blocking', 'fact_index': 1, 'reason': '不存在的条目'}], 'summary': '核对'})
    assert await StoryFact.filter(commit=baseline).count() == 1


@pytest.mark.asyncio
async def test_story_evidence_prevents_chapter_deletion_and_renumbering(project):
    from controllers.chapter import chapter_controller
    from schemas.chapter import ChapterPatch
    await accept(project, await reviewed(project))
    chapter = await Chapter.create(novel=project, number=1, name='一', content='古城断水。')
    await pending(project, chapter)
    with pytest.raises(HTTPException, match='故事记忆'):
        await chapter_controller.remove(chapter.id)
    with pytest.raises(HTTPException, match='故事记忆'):
        await chapter_controller.patch(chapter.id, ChapterPatch(number=2))
    assert await Chapter.filter(id=chapter.id, number=1, content='古城断水。').exists()
