import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI

from api.novel import router
from auth.deps import AuthContext
from controllers.chapter import chapter_controller
from controllers.novel import novel_controller
from models.ai_task import AiTask
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from models.story_memory import StoryCommit, StoryMemoryProject, StorySnapshot
from schemas.novel import NovelCreate
from services.ai_task_executor import ai_task_executor
from services.chapter_screenplay import submit_screenplay
from services.story_memory.automatic import queue_memory
from services.story_memory.status import memory_status
from test.agent_stream_fixtures import completion_stream_response
from test.test_services.test_story_memory import candidate


MANUSCRIPT = '第1章 古城\n老周在古城守门。\n\n第2章 石桥\n老周从石桥进入隧道。\n\n第3章 新世界\n老周穿过隧道来到未来城。'


@pytest.fixture(autouse=True)
def local_workspace(monkeypatch):
    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)


async def model_config():
    return await AiModelConfig.create(name='strict-memory', model='strict', task_type=7,
        base_url='https://model.invalid/v1', api_key='synthetic', supports_strict_output=True, is_active=True)


def model_transport(monkeypatch, *, invalid_memory=False):
    requests = []

    def respond(req):
        body = json.loads(req.content)
        contract = body['response_format']['json_schema']
        assert contract['strict'] is True
        requests.append(body)
        context = json.loads(body['messages'][-1]['content'])['task_context']['input']
        if contract['name'] == 'story_memory_extract':
            source = context['source_snapshot']
            chapter = source['chapter']
            if chapter:
                reply = candidate(chapter['text'], source='chapter.text', content='老周进入未来城。')
                reply['subjects'][0]['name'] = '未来城'
            else:
                reply = candidate(source['opening_chapter']['text'], source='opening_chapter.text', content='老周最初住在古城。')
                reply['facts'][0]['evidence'][0]['quote'] = '模型的摘录略有出入。'
            subject = reply['subjects'][0]
            subject['existing_id'] = next((item['id'] for item in context['subjects'] if item['name'] == subject['name']), None)
            if invalid_memory:
                reply['facts'][0]['subject_ref'] = '不存在的对象'
        elif contract['name'] == 'screenplay':
            reply = {'screenplay': '3-1 未来城 外 日\n△ 老周走出隧道。'}
        else:
            assert contract['name'] == 'assets'
            reply = {'persons': [], 'scenes': [], 'items': []}
        return completion_stream_response({'id': 'strict', 'created': 1, 'model': 'strict',
            'object': 'chat.completion', 'choices': [{'index': 0, 'message': {
                'role': 'assistant', 'content': json.dumps(reply, ensure_ascii=False)}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})

    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    return requests


@pytest.mark.asyncio
async def test_multi_chapter_split_queues_one_global_task_and_target_episode_autocommits(monkeypatch):
    await model_config()
    requests = model_transport(monkeypatch)
    project = await Novel.create(name='故城', content=MANUSCRIPT)
    app = FastAPI()
    app.include_router(router, prefix='/novel')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(f'/novel/{project.id}/split')
        assert response.status_code == 200, response.text
    assert await StoryMemoryProject.filter(novel=project).count() == 1
    baseline = await StoryCommit.get(novel=project, chapter_id=None)
    assert baseline.status == 'pending' and not requests
    await ai_task_executor.run(await baseline.task)
    await baseline.refresh_from_db()
    assert baseline.status == 'accepted' and baseline.decided_by is None and baseline.review == {}
    assert await StorySnapshot.filter(commit=baseline).exists()

    episode = await Chapter.get(novel=project, number=3)
    screenplay = await submit_screenplay(episode.id, AuthContext())
    await ai_task_executor.run(screenplay)
    await screenplay.refresh_from_db()
    assert screenplay.status == 3, screenplay.error_message
    assert [item['response_format']['json_schema']['name'] for item in requests] == [
        'story_memory_extract', 'story_memory_extract', 'screenplay']
    episode_context = json.loads(requests[1]['messages'][-1]['content'])['task_context']['input']
    assert episode_context['source_snapshot']['preceding_excerpt']['number'] == 2
    assert not await StoryCommit.filter(novel=project, chapter__number__in=[1, 2]).exists()
    saved = await StoryCommit.get(chapter=episode, status='accepted')
    assert saved.status == 'accepted' and saved.parent_id == baseline.id
    prompt = json.loads(requests[2]['messages'][-1]['content'])
    memory = prompt['task_context']['input']['story_memory']
    assert memory['commit_id'] == saved.id and memory['baseline_commit_id'] == baseline.id
    assert {item['name'] for item in memory['worlds']} == {'故城世界', '未来城'}
    assert '老周穿过隧道来到未来城' in prompt['task_context']['input']['source_text']
    assert 'story_memory' not in json.dumps(prompt['creative_method'])
    assert 'Story memory language' not in requests[2]['messages'][0]['content']

    queued = await StoryCommit.get(chapter=episode, status='pending')
    assert queued.source_snapshot['chapter']['kind'] == 'screenplay'
    assert queued.replaces_id == saved.id
    after_save = await queued.task
    assert after_save.status == 1
    await ai_task_executor.run(after_save)
    await queued.refresh_from_db()
    assert queued.status == 'accepted'
    assert (await memory_status(project.id))['chapters'][2]['state'] == 'current'

    for _ in range(2):
        extraction = await chapter_controller.extract(episode.id)
        await ai_task_executor.run(extraction)
        await extraction.refresh_from_db()
        assert extraction.status == 3, extraction.error_message
    assert [item['response_format']['json_schema']['name'] for item in requests[3:]] == [
        'story_memory_extract', 'assets', 'assets']
    await saved.refresh_from_db()
    assert saved.status == 'accepted' and await StorySnapshot.filter(commit=saved).exists()
    latest = await StoryCommit.filter(chapter=episode.id, status='accepted').order_by('-id').first()
    assert latest.source_snapshot['chapter']['kind'] == 'screenplay'
    assert latest.replaces_id == saved.id
    assert (await memory_status(project.id))['baseline']['state'] == 'current'

    await episode.refresh_from_db()
    identical = await submit_screenplay(episode.id, AuthContext(), expected_screenplay=episode.screenplay)
    await ai_task_executor.run(identical)
    await identical.refresh_from_db()
    assert identical.status == 3 and len(requests) == 7
    assert await StoryCommit.filter(chapter=episode).count() == 2


@pytest.mark.asyncio
async def test_pasted_single_chapter_and_screenplay_do_not_enable_global_memory():
    await model_config()
    single = await novel_controller.create(NovelCreate(name='单章', content='只有这一章的故事。'))
    await novel_controller.split(single.id, ctx=AuthContext())
    screenplay = await novel_controller.create(NovelCreate(name='单剧本', content='场景一 古城 外 日\n△ 老周开门。', source_kind='screenplay'))
    assert not await StoryMemoryProject.all().exists()
    assert not await StoryCommit.all().exists()
    assert not await AiTask.all().exists()
    for project in (single, screenplay):
        assert not (await memory_status(project.id))['automatic']


@pytest.mark.asyncio
async def test_concurrent_requests_share_the_queued_baseline_even_after_edit_then_undo(monkeypatch):
    await model_config()
    requests = model_transport(monkeypatch)
    project = await Novel.create(name='故城', content=MANUSCRIPT)
    await novel_controller.split(project.id, ctx=AuthContext())
    initial = await StoryCommit.get(novel=project, chapter_id=None)
    original_task = await initial.task
    first = await Chapter.get(novel=project, number=1)
    before = first.content
    first.content = '老周搬到未来城。'
    await first.save(update_fields=['content'])
    first.content = before
    await first.save(update_fields=['content'])
    await ai_task_executor.run(original_task)
    await initial.refresh_from_db()
    assert initial.status == 'stale' and not requests

    queued = await asyncio.gather(*(queue_memory(project.id, None, AuthContext()) for _ in range(2)))
    assert queued[0].id == queued[1].id and queued[0].id != original_task.id
    await asyncio.gather(*(ai_task_executor.run(task) for task in queued))
    assert len(requests) == 1
    assert await StoryCommit.filter(novel=project, chapter_id=None, status='accepted').count() == 1


@pytest.mark.asyncio
async def test_missing_or_failed_optional_memory_does_not_stop_creation(monkeypatch):
    project = await Novel.create(name='故城', content=MANUSCRIPT)
    await novel_controller.split(project.id, ctx=AuthContext())
    assert await StoryMemoryProject.filter(novel=project).exists()
    assert not await StoryCommit.filter(novel=project).exists()
    await model_config()
    requests = model_transport(monkeypatch, invalid_memory=True)
    episode = await Chapter.get(novel=project, number=3)
    task = await submit_screenplay(episode.id, AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert [item['response_format']['json_schema']['name'] for item in requests] == ['story_memory_extract', 'screenplay']
    body = json.loads(requests[1]['messages'][-1]['content'])
    assert 'story_memory' not in body['task_context']['input']
    assert not await StorySnapshot.filter(novel=project).exists()
