from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from api.story_memory import router
from auth.deps import AuthContext
from controllers.chapter import chapter_controller
from controllers.story_memory import submit_analysis
from models.ai_task import AiTask
from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from models.scene import Scene
from models.story_memory import StoryCommit, StoryFact, StorySnapshot, StorySubject
from schemas.chapter import ChapterPatch, EpisodePacing
from schemas.story_memory import StoryAnalysisRequest, StoryDecision, StoryRecheckRequest
from services.ai_task_executor import ai_task_executor
from services.creation_agent.object_state import write_fields
from services.creation_agent.skill_execution import SkillExecution
from services.creation_objects import CreationObjects, project_write
from services.story_memory.recheck import submit_recheck, resume_recheck
from services.story_memory.status import memory_status
from services.story_memory.store import commit_data, decide, save_candidate
from test.test_services.test_story_memory import accept, candidate, saved_candidate


@pytest.fixture(autouse=True)
def local_workspace(monkeypatch):
    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)


async def chain(count=3):
    project = await Novel.create(name='故城', project_setting='古代王朝，没有电力。', story_outline='邻居守护城门。')
    chapters = [await Chapter.create(novel=project, number=i, name=f'第{i}集', content=f'原文{i}', screenplay=f'古城第{i}夜断水。') for i in range(1, count + 1)]
    baseline = await accept(project, await saved_candidate(project))
    subject = await StorySubject.get(novel=project)
    commits = []
    for chapter in chapters:
        payload = candidate(chapter.screenplay, source='chapter.text', existing_id=subject.id, content=chapter.screenplay)
        commits.append(await accept(project, await saved_candidate(project, chapter, payload)))
    return project, chapters, [baseline, *commits]


async def strict_model():
    return await AiModelConfig.create(name='story-memory', model='strict', task_type=7,
        base_url='https://model.invalid', api_key='synthetic', supports_strict_output=True, is_active=True)


def generation(monkeypatch, calls):
    async def generate(self, facts):
        stage = self.params['output_contract']['name']
        calls.append((stage, deepcopy(facts)))
        source = facts['source_snapshot']
        text = source['chapter']['text'] if source['chapter'] else source['project']['setting']
        return {'summary': text}
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)


@pytest.mark.asyncio
async def test_edit_invalidates_only_current_and_later_snapshots_without_erasing_history():
    project, chapters, commits = await chain()
    snapshots = [deepcopy((await StorySnapshot.get(commit=row)).data) for row in commits]
    fact_count = await StoryFact.all().count()
    asset = await Asset.create(novel=project, canonical_name='邻居', asset_type=1, base_traits='已有设计')
    scene = await Scene.create(chapter=chapters[1], sequence=1, prompt='已有分镜')
    await chapter_controller.patch(chapters[1].id, ChapterPatch(screenplay='古城恢复供水。'))
    state = await memory_status(project.id)
    assert state['baseline']['state'] == 'current'
    assert [item['state'] for item in state['chapters']] == ['current', 'stale', 'stale']
    assert state['chapters'][1]['can_analyze'] and not state['chapters'][2]['can_analyze']
    assert state['chapters'][2]['invalidation']['chapter_id'] == chapters[1].id
    assert state['chapters'][2]['invalidation']['reason'] == 'chapter_changed'
    assert (await StorySnapshot.get(commit=commits[1])).data == snapshots[1]
    assert await StoryFact.all().count() == fact_count
    assert (await StoryCommit.get(id=commits[2].id)).status == 'accepted'
    assert commits[2].source_snapshot['chapter']['text'] == '古城第2夜断水。'
    assert (await Asset.get(id=asset.id)).base_traits == '已有设计'
    assert (await Scene.get(id=scene.id)).prompt == '已有分镜'


@pytest.mark.asyncio
async def test_noop_pacing_and_preserved_original_do_not_invalidate_production_memory():
    project, chapters, _ = await chain()
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay=chapters[0].screenplay))
    await chapter_controller.patch(chapters[0].id, ChapterPatch(content='修改原著，当前导演稿保持不变。'))
    await chapter_controller.patch(chapters[0].id, ChapterPatch(episode_pacing=EpisodePacing(preset='fast')))
    project.description = ''  # Same canonical context as the previously absent description.
    await project.save(update_fields=['description'])
    assert all(item['state'] == 'current' for item in (await memory_status(project.id))['chapters'])


@pytest.mark.asyncio
async def test_undo_and_direct_save_share_invalidation_and_do_not_revive_old_approval():
    project, chapters, commits = await chain()
    chapter = chapters[0]
    chapter.screenplay = '邻居离开古城。'
    await chapter.save(update_fields=['screenplay'])
    await write_fields(CreationObjects(project.id), chapter, {'screenplay': '古城第1夜断水。'})
    assert (await Chapter.get(id=chapter.id)).screenplay == commits[1].source_snapshot['chapter']['text']
    assert all(item['state'] == 'stale' for item in (await memory_status(project.id))['chapters'])
    assert not (await commit_data(commits[1]))['current']


@pytest.mark.asyncio
async def test_global_edit_and_reverted_setting_still_require_reapproval():
    project, _, _ = await chain()
    project.project_setting = '未来世界。'
    await project.save(update_fields=['project_setting'])
    project.project_setting = '古代王朝，没有电力。'
    await project.save(update_fields=['project_setting'])
    state = await memory_status(project.id)
    assert state['baseline']['state'] == 'stale'
    assert all(item['state'] == 'stale' for item in state['chapters'])
    assert not state['chapters'][0]['can_analyze']


@pytest.mark.asyncio
async def test_source_write_and_invalidation_rollback_together():
    project, chapters, _ = await chain()
    with pytest.raises(RuntimeError):
        async with project_write(project.id):
            await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='未完成的改稿'))
            raise RuntimeError('later write failed')
    assert (await Chapter.get(id=chapters[0].id)).screenplay == '古城第1夜断水。'
    assert all(item['state'] == 'current' for item in (await memory_status(project.id))['chapters'])


@pytest.mark.asyncio
async def test_reanalysis_supersedes_only_its_chapter_and_carries_previous_edition(monkeypatch):
    project, chapters, commits = await chain()
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[1].id, ChapterPatch(screenplay='古城重新供水。'))
    task = await submit_analysis(project.id, StoryAnalysisRequest(request_id=uuid4(), chapter_id=chapters[1].id), AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    row = await StoryCommit.get(task=task)
    assert row.replaces_id == commits[2].id and row.parent_id == commits[1].id
    assert calls[0][1]['previous']['summary'] == commits[1].candidate['summary']
    assert calls[0][1]['baseline_summary'] == commits[0].candidate['summary']
    assert calls[0][1]['source_snapshot']['chapter']['text'] == '古城重新供水。'
    assert '古城第2夜断水' not in str(calls[0][1])
    await accept(project, row)
    state = await memory_status(project.id)
    assert [item['state'] for item in state['chapters']] == ['current', 'current', 'stale']
    assert (await StorySnapshot.get(commit=commits[2])).data['fact_ids']
    assert commits[2].source_snapshot['chapter']['text'] == '古城第2夜断水。'


@pytest.mark.asyncio
async def test_recheck_advances_in_order_and_pauses_for_each_human_decision(monkeypatch):
    project, chapters, commits = await chain()
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[1].id, ChapterPatch(screenplay='古城重新供水。'))
    request = StoryRecheckRequest(request_id=uuid4(), from_chapter_id=chapters[1].id)
    batch = await submit_recheck(project.id, request, AuthContext())
    assert (await submit_recheck(project.id, request, AuthContext())).id == batch.id
    await ai_task_executor.run(batch)
    await batch.refresh_from_db()
    assert batch.status == 2 and batch.stage == 'needs_review', batch.error_message
    assert batch.response_data['total'] == 2 and not batch.response_data['completed']
    waiting = await StoryCommit.get(id=batch.response_data['waiting_commit_id'])
    assert waiting.chapter_id == chapters[1].id and waiting.status == 'ready'
    row = (await memory_status(project.id))['chapters'][1]
    assert row['state'] == 'stale' and row['candidate_id'] == waiting.id and row['candidate_status'] == 'ready'
    with pytest.raises(HTTPException, match='已有待处理候选'):
        await submit_analysis(project.id, StoryAnalysisRequest(request_id=uuid4(), chapter_id=waiting.chapter_id), AuthContext())
    from controllers.creation_agent import creation_agent_controller
    from models.creation_agent import AgentMessage
    message = await AgentMessage.get(task_id=batch.id, role='assistant')
    history = await creation_agent_controller.messages(message.conversation_id, AuthContext(), before=None)
    assert all(item['task_id'] != str(waiting.task_id) for item in history['items'])
    run = await creation_agent_controller.snapshot(batch.id, AuthContext())
    assert any(item['task_id'] == str(waiting.task_id) for item in run.production)
    assert len(calls) == 1
    assert (await memory_status(project.id))['chapters'][2]['state'] == 'stale'
    await accept(project, waiting)
    resumed = await resume_recheck(waiting)
    assert resumed and resumed.status == 6
    assert await resume_recheck(waiting) is None
    await ai_task_executor.run(resumed)
    await batch.refresh_from_db()
    second = await StoryCommit.get(id=batch.response_data['waiting_commit_id'])
    assert second.chapter_id == chapters[2].id and second.parent_id == waiting.id
    assert await resume_recheck(waiting) is None  # An old decision cannot wake a later confirmation.
    assert len(calls) == 2
    await accept(project, second)
    await ai_task_executor.run(await resume_recheck(second))
    await batch.refresh_from_db()
    assert batch.status == 3 and batch.response_data['state'] == 'completed', batch.error_message
    assert len(calls) == 2  # Resuming never repeats accepted model work.
    assert all(item['state'] == 'current' for item in (await memory_status(project.id))['chapters'])
    assert (await StoryCommit.get(id=commits[3].id)).status == 'accepted'


@pytest.mark.asyncio
async def test_edited_candidate_stays_confirmable_and_continues_the_same_batch(monkeypatch):
    project, chapters, _ = await chain(count=1)
    await strict_model()
    source = '古城重新供水。水由新建水井供应。'
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay=source))
    calls = []
    generation(monkeypatch, calls)
    batch = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4(), from_chapter_id=chapters[0].id), AuthContext())
    await ai_task_executor.run(batch)
    await batch.refresh_from_db()
    waiting = await StoryCommit.get(id=batch.response_data['waiting_commit_id'])
    proposal = deepcopy(waiting.candidate)
    proposal['summary'] = '水由新建水井供应。'
    edited = await save_candidate(project.id, waiting.id, proposal, waiting.revision)
    assert edited.status == 'ready' and edited.revision == waiting.revision + 1
    assert edited.review == {} and not await StorySnapshot.filter(commit_id=waiting.id).exists()

    app = FastAPI()
    app.include_router(router)
    url = f'/novel/{project.id}/story-memory/commits/{waiting.id}/decision'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(url, json={'decision': 'accept', 'expected_package_hash': waiting.package_hash})
        assert response.status_code == 409
        response = await client.post(url, json={'decision': 'accept', 'expected_package_hash': edited.package_hash})
        assert response.status_code == 200, response.text
    await batch.refresh_from_db()
    assert batch.status == 3 and len(calls) == 1
    assert (await StorySnapshot.get(commit_id=waiting.id)).data['summary'] == '水由新建水井供应。'


@pytest.mark.asyncio
async def test_rejection_stops_downstream_work_and_retains_all_old_records(monkeypatch):
    project, chapters, commits = await chain()
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='邻居离开。'))
    batch = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(batch)
    await batch.refresh_from_db()
    row = await StoryCommit.get(id=batch.response_data['waiting_commit_id'])
    await decide(project.id, row.id, StoryDecision(expected_package_hash=row.package_hash, decision='reject', note='设定不符'), 7)
    await ai_task_executor.run(await resume_recheck(row))
    await batch.refresh_from_db()
    assert batch.status == 4 and '退回' in batch.error_message
    assert len(calls) == 1
    assert await StoryCommit.filter(id__in=[c.id for c in commits], status='accepted').count() == 4


@pytest.mark.asyncio
async def test_edits_while_waiting_stop_batch_without_replaying_paid_work(monkeypatch):
    project, chapters, _ = await chain()
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='古城停电。'))
    batch = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(batch)
    await batch.refresh_from_db()
    row = await StoryCommit.get(id=batch.response_data['waiting_commit_id'])
    await accept(project, row)
    await chapter_controller.patch(chapters[2].id, ChapterPatch(screenplay='新的末日设定。'))
    await ai_task_executor.run(await resume_recheck(row))
    await batch.refresh_from_db()
    assert batch.status == 4 and '再次变化' in batch.error_message
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fresh_batch_skips_current_chapters_without_model_calls(monkeypatch):
    project, _, _ = await chain()
    await strict_model()
    mock = AsyncMock(side_effect=AssertionError('current memory must not call a model'))
    monkeypatch.setattr(SkillExecution, 'generate_strict', mock)
    batch = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(batch)
    await batch.refresh_from_db()
    assert batch.status == 3 and len(batch.response_data['completed']) == 4
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_endpoint_and_decision_resume_the_same_batch(monkeypatch):
    project, chapters, _ = await chain(count=1)
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='邻居守住木门。'))
    app = FastAPI()
    app.include_router(router)
    url = f'/novel/{project.id}/story-memory'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        state = (await client.get(url + '/status')).json()['data']
        assert state['chapters'][0]['state'] == 'stale'
        response = await client.post(url + '/recheck', json={'request_id': str(uuid4())})
        assert response.status_code == 200, response.text
        batch = await AiTask.get(id=response.json()['data']['id'])
        row = await StoryCommit.get(id=batch.response_data['waiting_commit_id'])
        response = await client.post(url + f'/commits/{row.id}/decision', json={
            'expected_package_hash': row.package_hash, 'decision': 'accept'})
        assert response.status_code == 200, response.text
        await batch.refresh_from_db()
        assert batch.status == 3 and batch.response_data['state'] == 'completed'


@pytest.mark.asyncio
async def test_pending_approval_cannot_revive_after_edit_then_undo():
    project, chapters, _ = await chain()
    subject = await StorySubject.get(novel=project)
    row = await saved_candidate(project, chapters[1], candidate(chapters[1].screenplay,
        source='chapter.text', existing_id=subject.id))
    original_candidate = row.candidate
    await chapter_controller.patch(chapters[1].id, ChapterPatch(screenplay='改成未来世界。'))
    await chapter_controller.patch(chapters[1].id, ChapterPatch(screenplay=chapters[1].screenplay))
    row = await StoryCommit.get(id=row.id)
    assert row.status == 'stale' and row.candidate == original_candidate
    with pytest.raises(HTTPException):
        await accept(project, row)
    assert not (await commit_data(row))['current']


@pytest.mark.asyncio
async def test_new_chapter_inserted_before_existing_chapters_invalidates_the_suffix():
    project, _, _ = await chain(count=0)
    subject = await StorySubject.get(novel=project)
    chapters = []
    for number in (2, 3):
        chapter = await Chapter.create(novel=project, number=number, name=f'第{number}集', content=f'古城第{number}夜断水。')
        await accept(project, await saved_candidate(project, chapter,
            candidate(chapter.content, source='chapter.text', existing_id=subject.id)))
        chapters.append(chapter)
    # Inserting a newly imported earlier episode changes the required predecessor chain.
    await Chapter.create(novel=project, number=1, name='序章', content='古城此前尚未断水。')
    state = await memory_status(project.id)
    assert state['chapters'][0]['state'] == 'missing'
    assert [item['state'] for item in state['chapters'][1:]] == ['stale'] * len(chapters)
    assert state['chapters'][1]['invalidation']['reason'] == 'chapter_inserted'


@pytest.mark.asyncio
async def test_generated_screenplay_invalidates_memory_in_its_save_transaction(monkeypatch):
    from services.chapter_screenplay import submit_screenplay
    project, chapters, _ = await chain()
    await strict_model()
    monkeypatch.setattr(SkillExecution, 'generate_strict', AsyncMock(return_value={'screenplay': '新导演稿：邻居撤离。'}))
    task = await submit_screenplay(chapters[0].id, AuthContext(), chapters[0].screenplay)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert (await Chapter.get(id=chapters[0].id)).content == '原文1'
    assert all(item['state'] == 'stale' for item in (await memory_status(project.id))['chapters'])


@pytest.mark.asyncio
async def test_agent_script_edit_and_undo_keep_history_but_require_new_memory():
    from models.creation_agent import AgentConversation, AgentMessage
    from schemas.creation_agent import AgentRunRequest
    from services.creation_agent.changes import CreationChanges
    project, chapters, commits = await chain()
    chapter = chapters[0]
    task = await AiTask.create(task_type=7, status=2, request_params={'novel_id': project.id})
    conversation = await AgentConversation.create(novel=project)
    request = AgentRunRequest(request_id=task.id, message='修改本集导演稿', write_scope='chapter', chapter_id=chapter.id)
    await AgentMessage.create(task=task, conversation=conversation, role='user', request_id=task.id,
        request_hash='script', run_input=request.model_dump(mode='json'))
    service = CreationChanges(novel_id=project.id, task_id=task.id, request=request, max_batch_size=10)
    await service.read_episode_script(chapter.id)
    change = await service.revise_episode_script(chapter.id, '邻居改为守护水井。', None, 'revise-script')
    assert all(item['state'] == 'stale' for item in (await memory_status(project.id))['chapters'])
    await service.undo(change.id)
    assert (await Chapter.get(id=chapter.id)).screenplay == chapter.screenplay
    assert all(item['state'] == 'stale' for item in (await memory_status(project.id))['chapters'])
    assert await StoryCommit.filter(id__in=[commit.id for commit in commits], status='accepted').count() == 4


@pytest.mark.asyncio
async def test_cancelled_batch_cannot_be_restarted_by_a_late_decision(monkeypatch):
    from services.task_cancellation import cancel_task
    project, chapters, _ = await chain()
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='邻居离开。'))
    batch = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(batch)
    await batch.refresh_from_db()
    row = await StoryCommit.get(id=batch.response_data['waiting_commit_id'])
    await cancel_task(batch.id)
    await accept(project, row)
    assert await resume_recheck(row) is None
    assert (await AiTask.get(id=batch.id)).status == 5
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_recheck_requests_reject_foreign_or_blocked_starts_and_parallel_batches(monkeypatch):
    project, chapters, _ = await chain()
    await strict_model()
    other = await Novel.create(name='另一部作品')
    foreign = await Chapter.create(novel=other, number=1, name='另一集', content='另一个故事')
    with pytest.raises(HTTPException) as error:
        await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4(), from_chapter_id=foreign.id), AuthContext())
    assert error.value.status_code == 404
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='新的故事前情。'))
    with pytest.raises(HTTPException, match='第 1 章'):
        await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4(), from_chapter_id=chapters[1].id), AuthContext())
    request = StoryRecheckRequest(request_id=uuid4())
    await submit_recheck(project.id, request, AuthContext())
    with pytest.raises(HTTPException, match='已有故事复核'):
        await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    with pytest.raises(HTTPException, match='同一请求'):
        await submit_recheck(project.id, request.model_copy(update={'from_chapter_id': chapters[0].id}), AuthContext())


@pytest.mark.asyncio
async def test_recovery_reuses_awaiting_candidate_without_repeating_model_calls(monkeypatch):
    from services.creation_agent.recovery import ProductionRecovery
    project, chapters, _ = await chain()
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='邻居离开。'))
    batch = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(batch)
    await batch.refresh_from_db()
    waiting = batch.response_data['waiting_commit_id']
    await ProductionRecovery().recover()
    recovered = await AiTask.get(id=batch.id)
    assert recovered.status == 6
    await ai_task_executor.run(recovered)
    recovered = await AiTask.get(id=batch.id)
    assert recovered.stage == 'needs_review' and recovered.response_data['waiting_commit_id'] == waiting
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_recheck_and_status_keep_existing_team_and_role_boundaries(monkeypatch):
    from types import SimpleNamespace
    from auth.deps import get_auth_context
    project, _, _ = await chain(count=1)
    project.team_id = 11
    await project.save(update_fields=['team_id'])
    monkeypatch.setattr('config.settings.AUTH_ENABLED', True)
    ctx = AuthContext(user=SimpleNamespace(id=7), team_id=11, membership=SimpleNamespace(role='viewer'))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    url = f'/novel/{project.id}/story-memory'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get(url + '/status')).status_code == 200
        assert (await client.post(url + '/recheck', json={'request_id': str(uuid4())})).status_code == 403
        ctx.team_id = 22
        assert (await client.get(url + '/status')).status_code == 404
        assert (await client.post(url + '/recheck', json={'request_id': str(uuid4())})).status_code == 404


@pytest.mark.asyncio
async def test_status_uses_bounded_queries_for_a_multi_chapter_project(monkeypatch):
    from tortoise import Tortoise
    project, _, _ = await chain(count=12)
    connection = Tortoise.get_connection('default')
    execute = AsyncMock(wraps=connection.execute_query)
    execute_dict = AsyncMock(wraps=connection.execute_query_dict)
    monkeypatch.setattr(connection, 'execute_query', execute)
    monkeypatch.setattr(connection, 'execute_query_dict', execute_dict)
    state = await memory_status(project.id)
    assert len(state['chapters']) == 12 and all(item['state'] == 'current' for item in state['chapters'])
    assert execute.await_count + execute_dict.await_count <= 8


@pytest.mark.asyncio
async def test_new_edition_recheck_stops_obsolete_batch_and_keeps_its_candidate(monkeypatch):
    project, chapters, _ = await chain()
    await strict_model()
    calls = []
    generation(monkeypatch, calls)
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='邻居离开。'))
    old = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    await ai_task_executor.run(old)
    await old.refresh_from_db()
    previous = old.response_data['waiting_commit_id']
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='邻居留下修好水井。'))
    new = await submit_recheck(project.id, StoryRecheckRequest(request_id=uuid4()), AuthContext())
    assert new.id != old.id and (await AiTask.get(id=old.id)).status == 5
    assert (await StoryCommit.get(id=previous)).candidate
    await ai_task_executor.run(new)
    await new.refresh_from_db()
    assert new.status == 2 and new.stage == 'needs_review'
    assert new.response_data['waiting_commit_id'] != previous
