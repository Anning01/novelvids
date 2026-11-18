import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI

from api.story_memory import router
from auth.deps import AuthContext, get_auth_context
from models.chapter import Chapter
from models.novel import Novel
from models.story_memory import StoryCommit, StoryFact, StorySnapshot
from test.agent_stream_fixtures import completion_stream_response
from test.test_services.test_story_memory import candidate, pending, reviewed, accept


@pytest.mark.asyncio
async def test_api_history_edit_and_decision_enforce_project_and_role(monkeypatch):
    monkeypatch.setattr('config.settings.AUTH_ENABLED', True)
    project = await Novel.create(name='故城', team_id=11, project_setting='古代王朝，没有电力。')
    foreign = await Novel.create(name='别人的故事', team_id=22)
    row = await reviewed(project)
    other = await pending(foreign)
    ctx = AuthContext(user=SimpleNamespace(id=7), membership=SimpleNamespace(role='viewer'), team_id=11)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    url = f'/novel/{project.id}/story-memory'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        history = (await client.get(url + '/commits')).json()['data']
        assert len(history) == 1 and history[0]['id'] == row.id
        assert 'candidate' not in history[0]
        detail = (await client.get(url + f'/commits/{row.id}')).json()['data']
        assert detail['candidate']['facts'] and not detail['snapshot']
        assert (await client.get(url + f'/commits/{other.id}')).status_code == 404
        assert (await client.get(f'/novel/{foreign.id}/story-memory/commits')).status_code == 404
        decision = {'expected_package_hash': row.package_hash, 'decision': 'accept', 'note': '已核对'}
        assert (await client.post(url + f'/commits/{row.id}/decision', json=decision)).status_code == 403
        assert (await client.put(url + f'/commits/{row.id}/candidate', json={'expected_revision': 1, 'candidate': candidate()})).status_code == 403
        for path, body in [('/analyze', {'request_id': str(uuid4())}),
                           (f'/commits/{row.id}/review', {'expected_revision': 1}),
                           (f'/commits/{row.id}/repair', {'expected_revision': 1, 'expected_package_hash': row.package_hash})]:
            assert (await client.post(url + path, json=body)).status_code == 403
        ctx.membership.role = 'creator'
        assert (await client.post(url + f'/commits/{row.id}/decision', json={**decision, 'decided_by': 999})).status_code == 422
        accepted = (await client.post(url + f'/commits/{row.id}/decision', json=decision)).json()['data']
        assert accepted['status'] == 'accepted' and accepted['decided_by'] == 7
        facts = (await client.get(url + f'/commits/{row.id}/facts')).json()['data']
        subjects = (await client.get(url + '/subjects')).json()['data']
        assert len(facts) == len(subjects) == 1
        assert facts[0]['subject_id'] == subjects[0]['id']
        assert (await client.get(url + '/commits?limit=101')).status_code == 422
        assert (await client.get(url + f'/commits?before_id={row.id}')).json()['data'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('opening', [False, True])
async def test_http_task_uses_real_model_boundary_for_extraction_and_review(monkeypatch, opening):
    from models.ai_task import AiTask
    from models.config import AiModelConfig
    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)
    model = await AiModelConfig.create(name='strict', model='strict', task_type=7, supports_strict_output=True,
        base_url='https://model.invalid/v1', api_key='synthetic', is_active=True)
    text = '古代王朝，没有电力。'
    project = await Novel.create(name='故城', project_setting=None if opening else text)
    if opening:
        await Chapter.create(novel=project, number=1, name='开篇', content=text)
    proposed = candidate(source='opening_chapter.text' if opening else 'project.setting')
    if opening:
        proposed['unresolved'] = ['原文未写明具体朝代。']
    seen = []
    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        name = body['response_format']['json_schema']['name']
        if name == 'story_memory_extract':
            payload = proposed
        elif opening and len(seen) == 2:
            payload = {'issues': [{'severity': 'blocking', 'fact_index': None, 'reason': '缺少章末变化'}], 'summary': '需处理'}
        else:
            payload = {'issues': [], 'summary': '已核对'}
        return completion_stream_response({'id': 'story', 'created': 1, 'model': 'strict',
            'object': 'chat.completion', 'choices': [{'index': 0, 'message': {
                'role': 'assistant', 'content': json.dumps(payload, ensure_ascii=False)}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 25, 'completion_tokens': 12, 'total_tokens': 37}})
    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    app = FastAPI()
    app.include_router(router)
    url = f'/novel/{project.id}/story-memory'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(url + '/analyze', json={'request_id': str(uuid4())})
        assert response.status_code == 200, response.text
        row = await StoryCommit.get(novel=project)
        assert row.status == ('needs_review' if opening else 'ready'), (await row.task).error_message
        assert len(seen) == 2 and all(not call.get('tools') for call in seen)
        assert [call['response_format']['json_schema']['name'] for call in seen] == ['story_memory_extract', 'story_memory_review']
        assert not await StoryFact.all().exists()
        assert '古代王朝' in json.dumps(seen, ensure_ascii=False)
        if opening:
            assert row.source_snapshot['opening_chapter']['text'] == text
            assert row.candidate['facts'][0]['evidence'][0]['source'] == 'opening_chapter.text'
            old_hash, revision = row.package_hash, row.revision
            response = await client.post(url + f'/commits/{row.id}/review', json={'expected_revision': revision})
            assert response.status_code == 200, response.text
            review_task = await AiTask.get(id=response.json()['data']['id'])
            assert review_task.request_params['assistant_model_config_id'] == model.id
            assert len(seen) == 3 and seen[-1]['response_format']['json_schema']['name'] == 'story_memory_review'
            sent = json.dumps(seen[-1], ensure_ascii=False)
            assert '不因未逐条收录开篇剧情、章末能力变化、任务或奖励而阻断' in sent
            assert '未知项本身不构成问题' in sent and '原文未写明具体朝代' in sent
            await row.refresh_from_db()
            assert row.status == 'ready' and row.revision == revision and row.package_hash != old_hash
            assert row.candidate == proposed
            assert not await StorySnapshot.all().exists()
        result = await client.post(url + f'/commits/{row.id}/decision', json={
            'expected_package_hash': row.package_hash, 'decision': 'accept'})
        assert result.json()['data']['snapshot']['fact_ids']
        assert await StoryFact.all().count() == await StorySnapshot.all().count() == 1
        from models.creation_agent import AgentMessage
        messages = await AgentMessage.filter(task__request_params__not_isnull=True).all()
        # Both real provider calls have their own usage-bearing production message.
        assert len([m for m in messages if m.usage.get('requests')]) >= 2


@pytest.mark.asyncio
async def test_invalid_responses_enum_never_publishes_and_has_a_readable_assistant_error(monkeypatch):
    from api.creation_agent import router as assistant_router
    from models.config import AiModelConfig
    from test.test_services.test_strict_text_tasks import mock_model

    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)
    await AiModelConfig.create(name='strict', model='strict-model', task_type=7, supports_strict_output=True,
        base_url='https://model.invalid/v1', api_key='synthetic', is_active=True, text_api='responses')
    project = await Novel.create(name='故城', project_setting='古代王朝，没有电力。')
    previous = await accept(project, await reviewed(project))
    payload = candidate()
    payload['facts'][0].update(category='plan', nature='plan')
    seen = mock_model(monkeypatch, payload)
    app = FastAPI()
    app.include_router(router)
    app.include_router(assistant_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        submitted = (await client.post(f'/novel/{project.id}/story-memory/analyze',
            json={'request_id': str(uuid4())})).json()['data']
        from controllers.novel import novel_controller
        from models.ai_task import AiTask
        task = await AiTask.get(id=submitted['id'])
        assert task.status == 4 and 'facts.0.category' in task.error_message
        assert len(seen) == 1
        form = seen[0]['text']['format']
        assert form['type'] == 'json_schema' and form['strict'] is True
        props = form['schema']['$defs']['StoryFactProposal']['properties']
        assert 'plan' not in props['category']['enum'] and 'plan' in props['nature']['enum']
        assert 'plan 只能填在 nature' in json.dumps(seen[0]['input'], ensure_ascii=False)
        run = (await client.get(f"/runs/{submitted['id']}")).json()['data']
        assert '结果未入库' in run['error_message']
        assert run['production'][0]['error'] == run['error_message']
        assert (await novel_controller.latest_analysis(project.id)) is None
        assert await StorySnapshot.filter(commit_id=previous.id).count() == await StorySnapshot.all().count() == 1
        assert await StoryFact.all().count() == 1
