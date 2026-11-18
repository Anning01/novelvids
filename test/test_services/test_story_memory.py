import asyncio
from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from auth.deps import AuthContext
from controllers.story_memory import submit_analysis
from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.story_memory import StoryCommit, StoryFact, StorySnapshot, StorySubject
from schemas.story_memory import StoryAnalysisRequest, StoryCandidate, StoryDecision
from services.creation_agent.plan_sources import fingerprint
from services.story_memory.sources import latest_commit, predecessor, source_snapshot
from services.story_memory.store import commit_data, decide, package_hash, save_candidate


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


async def saved_candidate(project, chapter=None, payload=None):
    row = await pending(project, chapter)
    subject = await StorySubject.get_or_none(novel=project, name='故城世界')
    return await save_candidate(project.id, row.id, payload or candidate(existing_id=subject.id if subject else None), 1, initial=True)


async def accept(project, row, actor=17):
    return await decide(project.id, row.id, StoryDecision(expected_package_hash=row.package_hash,
        decision='accept', note='确认本次候选。'), actor)


@pytest.mark.asyncio
async def test_global_memory_uses_bounded_opening_when_only_import_metadata_exists():
    from services.story_memory.status import memory_status

    book = await Novel.create(name='导入作品', description='导入文件.txt')
    await Chapter.create(novel=book, number=1, name='空白卷首', content='\n')
    quote = '开篇的古城没有电力。'
    opening = await Chapter.create(novel=book, number=2, name='开篇', content=quote + '文' * 6100, screenplay='   ')
    later = await Chapter.create(novel=book, number=3, name='后文', content='后来建立了电网。')
    source = await source_snapshot(book.id)
    assert source['chapter'] is None
    assert source['opening_chapter']['id'] == opening.id
    assert source['opening_chapter']['kind'] == 'source'
    assert len(source['opening_chapter']['text']) == 6000
    assert '后来建立了电网' not in str(source)
    payload = candidate(quote, source='opening_chapter.text')
    baseline = await accept(book, await saved_candidate(book, payload=payload))
    assert (await memory_status(book.id))['baseline']['state'] == 'current'
    later.content = '后文经过修改。'
    await later.save(update_fields=['content'])
    assert (await memory_status(book.id))['baseline']['state'] == 'current'
    opening.screenplay = '开篇剧本设在没有电力的古城。'
    await opening.save(update_fields=['screenplay'])
    assert (await source_snapshot(book.id))['opening_chapter']['kind'] == 'screenplay'
    assert (await memory_status(book.id))['baseline']['state'] == 'stale'
    opening.screenplay = '   '
    await opening.save(update_fields=['screenplay'])
    assert (await memory_status(book.id))['baseline']['state'] == 'stale'
    assert await StoryFact.filter(commit_id=baseline.id).exists()


@pytest.mark.asyncio
async def test_empty_global_candidate_is_valid_and_enables_chapter_analysis(project):
    from services.story_memory.status import memory_status
    chapter = await Chapter.create(novel=project, number=1, name='第一章', content='原文。')
    payload = {'subjects': [], 'facts': [], 'summary': '现有资料有限。', 'ending_state': '', 'unresolved': ['时代未定。']}
    row = await accept(project, await saved_candidate(project, payload=payload))
    snapshot = await StorySnapshot.get(commit=row)
    assert snapshot.data['fact_ids'] == []
    assert snapshot.data['unresolved'] == ['时代未定。']
    state = await memory_status(project.id)
    assert state['baseline']['state'] == 'current'
    assert state['chapters'][0]['can_analyze']
    assert await predecessor(project.id, chapter.id) == row.id

@pytest.mark.asyncio
async def test_candidate_confirmation_and_history_preserve_existing_data(project):
    chapter = await Chapter.create(novel=project, number=1, name='邻居', content='原文', screenplay='邻居守着木门。')
    asset = await Asset.create(novel=project, canonical_name='已有邻居', asset_type=1, base_traits='用户已保存的设计')
    row = await pending(project)
    row = await save_candidate(project.id, row.id, candidate(), 1, initial=True)
    assert row.status == 'ready' and row.review == {}
    assert not await StoryFact.all().exists() and not await StorySubject.all().exists()
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
    row = await saved_candidate(project)
    first, second = await asyncio.gather(accept(project, row), accept(project, row))
    assert first.id == second.id
    assert await StoryFact.all().count() == await StorySnapshot.all().count() == 1
    with pytest.raises(HTTPException, match='结束'):
        await decide(project.id, row.id, StoryDecision(expected_package_hash=row.package_hash, decision='reject'), 17)


@pytest.mark.asyncio
async def test_candidate_edit_invalidates_previous_version_and_can_be_rejected(project):
    row = await saved_candidate(project)
    old_hash = row.package_hash
    updated = await save_candidate(project.id, row.id, candidate(content='仅作为候选核对'), row.revision)
    assert updated.revision == 2 and updated.status == 'ready' and not updated.review
    with pytest.raises(HTTPException, match='变化'):
        await accept(project, row)
    with pytest.raises(HTTPException, match='变化'):
        await save_candidate(project.id, row.id, candidate(), 1)
    rejected = await decide(project.id, row.id, StoryDecision(expected_package_hash=updated.package_hash,
        decision='reject', note='退回修改'), 23)
    assert rejected.status == 'rejected' and rejected.decided_by == 23
    assert old_hash != rejected.package_hash and not await StoryFact.all().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['draft', 'needs_review'])
async def test_legacy_candidates_are_confirmable_and_keep_the_saved_review(project, status):
    row = await saved_candidate(project)
    row.status = status
    row.review = {'issues': [{'severity': 'blocking', 'fact_index': 0, 'reason': '旧审核意见'}]} if status == 'needs_review' else {}
    row.package_hash = package_hash(row)
    await row.save(update_fields=['status', 'review', 'package_hash'])
    accepted = await accept(project, row)
    assert accepted.status == 'accepted' and accepted.review == row.review
    assert await StoryFact.filter(commit=accepted).count() == 1

@pytest.mark.asyncio
async def test_changed_source_rejects_approval_and_retains_snapshot(project):
    row = await saved_candidate(project)
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
    wrong_source = candidate(source='chapter.text')
    for payload in (wrong_source, candidate(existing_id=foreign.id)):
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
    baseline = await accept(project, await saved_candidate(project))
    with pytest.raises(HTTPException, match='第 1 章'):
        await pending(project, second)
    subject = await StorySubject.get(novel=project)
    one = await accept(project, await saved_candidate(project, first, candidate(first.screenplay, source='chapter.text', existing_id=subject.id)))
    two = await saved_candidate(project, second, candidate(second.content, source='chapter.text', existing_id=subject.id))
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
    a, b = await saved_candidate(project), await saved_candidate(project)
    await accept(project, a)
    with pytest.raises(HTTPException, match='新的正式提交'):
        await accept(project, b)
    new = await accept(project, await saved_candidate(project))
    assert new.replaces_id == a.id and not (await commit_data(a))['current']
    assert (await commit_data(new))['current']


@pytest.mark.asyncio
async def test_replacements_retractions_and_rollback_are_atomic(project, monkeypatch):
    baseline = await accept(project, await saved_candidate(project))
    old_fact = await StoryFact.get(commit=baseline)
    subject = await StorySubject.get(id=old_fact.subject_id)
    first = await Chapter.create(novel=project, number=1, name='变化', content='古城出现电力。')
    payload = candidate(first.content, source='chapter.text', existing_id=subject.id)
    payload['facts'][0].update(operation='replace', replaces_id=old_fact.id, content=first.content)
    row = await saved_candidate(project, first, payload)
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
    retracted = await accept(project, await saved_candidate(project, second, payload))
    assert (await StorySnapshot.get(commit=retracted)).data['fact_ids'] == []
    assert await StoryFact.all().count() == 3  # Original and retraction evidence remain immutable.


@pytest.mark.asyncio
async def test_analysis_task_is_idempotent_and_uses_one_strict_call(project, monkeypatch):
    from models.config import AiModelConfig
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    await AiModelConfig.create(name='strict', model='strict', task_type=7,
        base_url='https://model.invalid', api_key='test', supports_strict_output=True, is_active=True)
    seen = []
    payload = {'summary': '古代王朝，没有电力。邻居的职业未明。'}

    async def generate(self, facts):
        seen.append((self.params['output_contract']['name'], facts))
        return payload

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
    assert row.status == 'ready' and row.review == {} and not await StoryFact.all().exists()
    assert [name for name, _ in seen] == ['story_memory_extract']
    assert seen[0][1]['source_snapshot']['project']['setting'] == project.project_setting
    assert row.candidate['summary'] == payload['summary'] and row.candidate['facts'] == []
    accepted = await accept(project, row)
    assert (await StorySnapshot.get(commit=accepted)).data['summary'] == payload['summary']
    assert not await StoryFact.all().exists()

@pytest.mark.asyncio
async def test_extraction_failure_creates_no_candidate_or_snapshot(project, monkeypatch):
    from models.config import AiModelConfig
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    await AiModelConfig.create(name='strict', model='strict', task_type=7,
        base_url='https://model.invalid', api_key='test', supports_strict_output=True, is_active=True)
    async def generate(self, facts):
        raise RuntimeError('model unavailable')
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)
    task = await submit_analysis(project.id, StoryAnalysisRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    row = await StoryCommit.get(task=task)
    assert task.status == 4 and row.status == 'pending'
    assert not row.candidate and not await StorySnapshot.all().exists()


@pytest.mark.asyncio
async def test_reanalysis_keeps_old_review_as_history_only(project, monkeypatch):
    from models.config import AiModelConfig
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    previous = await saved_candidate(project)
    previous.review = {'issues': [], 'summary': '旧审核记录', 'task_id': str(uuid4())}
    previous.package_hash = package_hash(previous)
    await previous.save(update_fields=['review', 'package_hash'])
    previous = await accept(project, previous)
    await AiModelConfig.create(name='strict', model='strict', task_type=7,
        base_url='https://model.invalid', api_key='test', supports_strict_output=True, is_active=True)
    contexts = []
    async def generate(self, context):
        contexts.append(context)
        return {'summary': '古代王朝，无电力。'}
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)
    task = await submit_analysis(project.id, StoryAnalysisRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(contexts) == 1
    assert contexts[0] == {'source_snapshot': previous.source_snapshot}
    assert (await StoryCommit.get(id=previous.id)).review['task_id'] == previous.review['task_id']


def test_prompt_language_and_strict_contracts():
    from prompts.story_memory import contract, method
    from prompts.text_tasks import render_text_task
    for language in ('zh', 'en'):
        system, content = render_text_task(language=language,
            skill=method({'instructions': '自定义方法', 'references': []}, language), context={})
        assert f'language={language}' in system + content
        assert '大纲计划' in content and '场景' in content and '前一世界' in content
        assert '自定义方法' in content
    schema = contract()
    assert schema['name'] == 'story_memory_extract' and schema['version'] == 2
    assert list(schema['schema']['properties']) == ['summary']

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
    row = await saved_candidate(project, payload=candidate(project.project_setting))
    row = await accept(project, row)
    fact = await StoryFact.get(commit=row)
    assert fact.evidence[0]['quote'] == project.project_setting


@pytest.mark.asyncio
async def test_same_name_requires_explicit_identity_and_old_aliases_are_preserved(project):
    await accept(project, await saved_candidate(project))
    subject = await StorySubject.get(novel=project)
    subject.aliases = ['旧称']
    await subject.save(update_fields=['aliases'])
    row = await pending(project)
    with pytest.raises(HTTPException, match='同名'):
        await save_candidate(project.id, row.id, candidate(), 1, initial=True)
    payload = candidate(existing_id=subject.id)
    payload['subjects'][0]['aliases'] = ['新称']
    saved = await save_candidate(project.id, row.id, payload, 1, initial=True)
    await subject.refresh_from_db()
    assert subject.aliases == ['旧称']
    await accept(project, saved)
    await subject.refresh_from_db()
    assert set(subject.aliases) == {'旧称', '新称'}


@pytest.mark.asyncio
async def test_invented_replacement_is_rejected(project):
    baseline = await accept(project, await saved_candidate(project))
    subject = await StorySubject.get(novel=project)
    chapter = await Chapter.create(novel=project, number=1, name='一', content='古城断水。')
    row = await pending(project, chapter)
    payload = candidate(chapter.content, source='chapter.text', existing_id=subject.id)
    payload['facts'][0].update(operation='replace', replaces_id=999999)
    with pytest.raises(HTTPException, match='有效事实'):
        await save_candidate(project.id, row.id, payload, 1, initial=True)
    payload['facts'][0].update(operation='add', replaces_id=None)
    await save_candidate(project.id, row.id, payload, 1, initial=True)
    assert await StoryFact.filter(commit=baseline).count() == 1


@pytest.mark.asyncio
async def test_story_evidence_prevents_chapter_deletion_and_renumbering(project):
    from controllers.chapter import chapter_controller
    from schemas.chapter import ChapterPatch
    await accept(project, await saved_candidate(project))
    chapter = await Chapter.create(novel=project, number=1, name='一', content='古城断水。')
    await pending(project, chapter)
    with pytest.raises(HTTPException, match='故事记忆'):
        await chapter_controller.remove(chapter.id)
    with pytest.raises(HTTPException, match='故事记忆'):
        await chapter_controller.patch(chapter.id, ChapterPatch(number=2))
    assert await Chapter.filter(id=chapter.id, number=1, content='古城断水。').exists()


@pytest.mark.asyncio
async def test_queued_v1_task_still_uses_its_original_candidate_format(project, monkeypatch):
    from models.config import AiModelConfig
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution

    await AiModelConfig.create(name='legacy', model='strict', task_type=7, supports_strict_output=True,
        base_url='https://model.invalid', api_key='synthetic', is_active=True)
    task = await submit_analysis(project.id, StoryAnalysisRequest(request_id=uuid4()), AuthContext())
    task.request_params['output_contract'].update(version=1, schema=StoryCandidate.model_json_schema())
    await task.save(update_fields=['request_params'])
    generate = AsyncMock(return_value=candidate())
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)
    await ai_task_executor.run(task)
    row = await StoryCommit.get(task=task)
    assert row.status == 'ready' and row.candidate == candidate()
    assert 'prior_facts' in generate.await_args.args[0]
