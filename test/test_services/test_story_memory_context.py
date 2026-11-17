import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from api.story_memory import router
from auth.deps import AuthContext
from controllers.chapter import chapter_controller
from controllers.novel import novel_controller
from models.ai_task import AiTask
from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from models.scene import Scene
from models.story_memory import StoryCommit, StorySnapshot, StorySubject
from schemas.chapter import ChapterPatch
from services.ai_task_executor import ai_task_executor
from services.creation_agent.deep_tools import read_story_memory
from services.creation_agent.skill_execution import SkillExecution
from services.story_memory.context import story_context, capture_binding, verify_bindings
from test.test_services.test_story_memory import candidate, reviewed, accept
from test.test_services.test_strict_text_tasks import mock_model


@pytest.fixture(autouse=True)
def local_workspace(monkeypatch):
    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)


@pytest.fixture
async def story():
    project = await Novel.create(name='故城', project_setting='古代王朝，没有电力。老周是一位守门人。', story_outline='邻居守护城门。')
    chapters = [await Chapter.create(novel=project, number=i, name=f'第{i}章', content=text, screenplay=text)
        for i, text in enumerate(['老周提油灯照亮木门。', '灾变后，老周带居民寻找水源。', '后来才揭晓老周别名周将军。'], 1)]
    base = candidate(project.project_setting)
    base['subjects'].append({'ref': 'neighbor', 'existing_id': None, 'kind': 'character', 'name': '老周', 'aliases': []})
    identity = deepcopy(base['facts'][0])
    identity.update(subject_ref='neighbor', category='identity', content='老周是一位古代守门人。')
    base['facts'].append(identity)
    baseline = await accept(project, await reviewed(project, payload=base))
    world = await StorySubject.get(novel=project, kind='world')
    neighbor = await StorySubject.get(novel=project, kind='character')
    commits = []
    for chapter in chapters:
        payload = candidate(chapter.screenplay, source='chapter.text', existing_id=world.id, content=chapter.screenplay)
        payload['subjects'].append({'ref': 'neighbor', 'existing_id': neighbor.id, 'kind': 'character', 'name': neighbor.name,
            'aliases': ['周将军'] if chapter.number == 3 else []})
        payload['facts'][0].update(subject_ref='neighbor', category='state')
        commits.append(await accept(project, await reviewed(project, chapter, payload)))
    await AiModelConfig.create(name='strict-memory', model='strict-model', task_type=7,
        base_url='https://model.invalid/v1', api_key='synthetic', supports_strict_output=True, is_active=True)
    return project, chapters, baseline, commits


@pytest.mark.asyncio
async def test_context_has_world_prior_state_and_current_changes_without_future_aliases(story):
    project, chapters, baseline, commits = story
    old = await story_context(project.id, chapters[0].id)
    assert old['baseline_commit_id'] == baseline.id and old['commit_id'] == commits[0].id
    assert any('古代王朝' in fact['content'] for fact in old['facts'])
    assert any('老周' in fact['content'] for fact in old['facts'])
    assert '周将军' not in json.dumps(old, ensure_ascii=False)
    assert '灾变后' not in json.dumps(old, ensure_ascii=False)
    current = await story_context(project.id, chapters[1].id)
    assert current['previous']['summary'] == commits[0].candidate['summary']
    assert any('灾变后' in fact['content'] for fact in current['facts'])
    latest = await story_context(project.id, chapters[2].id)
    assert '周将军' in json.dumps(latest, ensure_ascii=False)


@pytest.mark.asyncio
async def test_extraction_catalog_hides_future_scene_details_but_keeps_explicit_identity(story):
    from models.asset_variant import AssetVariant
    from services.extraction.context import ExtractionContextLoader
    from services.extraction.messages import ExtractionMessageBuilder
    project, chapters, _, _ = story
    person = await Asset.create(novel=project, canonical_name='老周', asset_type=1,
        base_traits='稳定人物外观', source_chapters=[1])
    variant = await AssetVariant.create(asset=person, name='老周·后章外套',
        description='后章剧情', base_traits='后章损伤细节', chapter_numbers=[3])
    future = await Asset.create(novel=project, canonical_name='灾后废墟', asset_type=2,
        base_traits='第三章才断裂的水管', source_chapters=[3])
    named = await Asset.create(novel=project, canonical_name='油灯', asset_type=3,
        description='第三章才发生的事件', base_traits='后章隐藏信息', source_chapters=[3])
    loader = ExtractionContextLoader()
    context = await loader.load(novel_id=project.id, chapter_id=chapters[0].id)
    payload = ExtractionMessageBuilder().build(context)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert '第三章才断裂的水管' not in encoded and '后章隐藏信息' not in encoded and '后章损伤细节' not in encoded
    assert future.id not in {asset.id for asset in context.assets}
    assert next(asset for asset in context.assets if asset.id==named.id).base_traits is None
    projection = next(asset for asset in context.assets if asset.id==person.id)
    assert projection.base_traits=='稳定人物外观' and projection.variants[0].id==variant.id
    await named.refresh_from_db()
    await future.refresh_from_db()
    await variant.refresh_from_db()
    assert named.base_traits=='后章隐藏信息' and future.base_traits=='第三章才断裂的水管' and variant.base_traits=='后章损伤细节'
    later = await loader.load(novel_id=project.id, chapter_id=chapters[2].id)
    assert next(asset for asset in later.assets if asset.id==future.id).base_traits=='第三章才断裂的水管'


@pytest.mark.asyncio
async def test_screenplay_uses_confirmed_predecessor_even_when_current_memory_is_stale(story):
    project, chapters, _, commits = story
    await chapter_controller.patch(chapters[1].id, ChapterPatch(screenplay='当前章正在改写。'))
    with pytest.raises(HTTPException) as error:
        await story_context(project.id, chapters[1].id, purpose='assets')
    assert error.value.status_code == 409
    before = await story_context(project.id, chapters[1].id, purpose='screenplay')
    assert before['commit_id'] == commits[0].id


@pytest.mark.asyncio
async def test_episode_ranges_hide_future_worlds_and_expired_local_facts():
    project = await Novel.create(name='故城', project_setting='古代王朝，没有电力。', story_outline='第三集计划前往未来城。')
    first = await Chapter.create(novel=project, number=1, name='古城', content='老周提着油灯。')
    third = await Chapter.create(novel=project, number=3, name='未来城', content='老周来到未来城。')
    base = candidate()
    base['subjects'].append({'ref': 'future', 'existing_id': None, 'kind': 'world', 'name': '未来城', 'aliases': []})
    planned = deepcopy(base['facts'][0])
    planned.update(subject_ref='future', category='outline', nature='plan', content=project.story_outline,
        scope={**planned['scope'], 'world_ref': 'future', 'from_chapter': 3},
        evidence=[{'source': 'project.outline', 'start': 0, 'end': len(project.story_outline), 'quote': project.story_outline}])
    base['facts'].append(planned)
    await accept(project, await reviewed(project, payload=base))
    ancient = await StorySubject.get(novel=project, name='故城世界')
    future = await StorySubject.get(novel=project, name='未来城')
    local = candidate(first.content, source='chapter.text', existing_id=ancient.id, content=first.content)
    local['facts'][0]['scope'].update(from_chapter=1, until_chapter=1)
    await accept(project, await reviewed(project, first, local))
    later = candidate(third.content, source='chapter.text', existing_id=future.id, content=third.content)
    later['subjects'][0]['name'] = '未来城'
    await accept(project, await reviewed(project, third, later))
    before = await story_context(project.id, first.id)
    after = await story_context(project.id, third.id)
    assert '未来城' not in json.dumps(before, ensure_ascii=False)
    assert any(world['name'] == '未来城' for world in after['worlds'])
    assert not any(fact['content'] == first.content for fact in after['facts'])
    assert any(fact['nature'] == 'plan' for fact in after['facts'])


@pytest.mark.asyncio
async def test_admission_blocks_stale_memory_before_any_provider_request(story, monkeypatch):
    project, chapters, _, _ = story
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='已修改的古代设定。'))
    generate = AsyncMock()
    monkeypatch.setattr(SkillExecution, 'generate_strict', generate)
    with pytest.raises(HTTPException) as error:
        await chapter_controller.extract(chapters[0].id)
    assert error.value.status_code == 409
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_binding_detects_newly_enabled_memory_for_legacy_requests():
    project = await Novel.create(name='故城', project_setting='古代王朝，没有电力。')
    frozen = await capture_binding(project.id, None, 'assets')
    assert not next(iter(frozen.values()))['enabled']
    await accept(project, await reviewed(project))
    with pytest.raises(HTTPException, match='生成期间'):
        await verify_bindings({'novel_id': project.id, 'story_memory_bindings': frozen})


@pytest.mark.asyncio
async def test_legacy_cached_output_is_not_relabelled_as_using_new_story_memory(story):
    from models.agent_operation import AgentOperation
    from models.creation_agent import AgentConversation, AgentMessage
    from services.creation_agent.strict_text import prepare_text_workflow
    project, chapters, _, _ = story
    params = await prepare_text_workflow({'novel_id': project.id, 'chapter_id': chapters[0].id}, 'assets')
    params.pop('story_memory_bindings')  # Simulate a task submitted before memory integration existed.
    task = await AiTask.create(task_type=1, status=2, request_params=params)
    conversation = await AgentConversation.create(novel=project)
    message = await AgentMessage.create(task=task, conversation=conversation, role='assistant', request_id=uuid4(), request_hash='legacy')
    previous = {'persons': [], 'scenes': [], 'items': []}
    await AgentOperation.create(task=task, key='model:strict:assets', state='completed', result=previous)
    execution = SkillExecution({**params, 'task_id': str(task.id)}, message, AsyncMock())
    with pytest.raises(HTTPException, match='旧生成结果未绑定故事记忆'):
        await execution.generate_strict({'chapter': chapters[0].screenplay})
    await task.refresh_from_db()
    assert 'story_memory_bindings' not in task.request_params
    assert (await AgentOperation.get(task=task, key='model:strict:assets')).result == previous


@pytest.mark.asyncio
async def test_asset_model_request_gets_confirmed_context_and_saved_asset_provenance(story, monkeypatch):
    project, chapters, _, commits = story
    from prompts.skill_pack import read_skill
    from services.language import generation_language
    language = await generation_language()
    specification = json.loads(read_skill('asset_contract'))[language]['person']
    payload = {'persons': [{'name': '老周', 'aliases': [], 'label': '人物', 'description': '守门的邻居',
        'design': '古代守门人，手提油灯，穿深棕布衣。', 'visual_fields': {field: '古代朴素布衣与稳定人物特征' for field in specification['fields']}, 'variant': None}], 'scenes': [], 'items': []}
    requests = mock_model(monkeypatch, payload)
    task = await chapter_controller.extract(chapters[0].id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1
    prompt = json.dumps(requests[0], ensure_ascii=False)
    assert 'story_memory' in prompt and '古代王朝' in prompt and '周将军' not in prompt
    asset = await Asset.get(novel=project, canonical_name='老周')
    assert asset.metadata['story_memory'][f'assets:{chapters[0].id}']['commit_id'] == commits[0].id


@pytest.mark.asyncio
async def test_storyboard_request_and_saved_shots_share_the_memory_binding(story, monkeypatch):
    from controllers.scene import scene_controller
    from test.test_services.test_prompt_language import _shot
    project, chapters, _, commits = story
    shot = _shot().model_dump(exclude={'prompt', 'sequence', 'reference_only_types'})
    shot.update(duration=4, visible_asset_names=[], actions=[{'start': 0, 'end': 4, 'text': '油灯照亮古城木门。'}],
        visual_prose='古城木门与油灯。', dialogue=[], narration=[], blocking_map=None)
    requests = mock_model(monkeypatch, {'shots': [shot]})
    task = await scene_controller.generate(chapters[0].id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert '古代王朝' in json.dumps(requests, ensure_ascii=False)
    scene = await Scene.get(chapter=chapters[0])
    assert scene.metadata['story_memory'][f'storyboard:{chapters[0].id}']['commit_id'] == commits[0].id


@pytest.mark.asyncio
async def test_memory_change_after_model_output_prevents_persistence_and_keeps_candidate(story, monkeypatch):
    from models.agent_operation import AgentOperation
    project, chapters, _, _ = story
    generate = SkillExecution.generate_strict
    async def concurrent_change(self, facts):
        result = await generate(self, facts)
        await accept(project, await reviewed(project))  # Same script, different formally accepted story edition.
        return result
    monkeypatch.setattr(SkillExecution, 'generate_strict', concurrent_change)
    mock_model(monkeypatch, {'persons': [], 'scenes': [], 'items': []})
    task = await chapter_controller.extract(chapters[0].id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4 and not await Asset.filter(novel=project).exists()
    assert await AgentOperation.filter(task=task, key='model:strict:assets', state='completed').exists()


@pytest.mark.asyncio
async def test_selected_scene_edit_receives_separate_chapter_contexts_and_freezes_both(story, monkeypatch):
    from models.creation_agent import AgentConversation, AgentMessage
    from prompts.text_tasks import scene_prompt_batch_method
    from schemas.text_task_contracts import scene_prompt_batch_contract
    from services.creation_agent.strict_text import prepare_text_workflow
    project, chapters, _, _ = story
    first = await Scene.create(chapter=chapters[0], sequence=1, prompt='古城木门。')
    second = await Scene.create(chapter=chapters[1], sequence=1, prompt='灾变后的古井。')
    params = await prepare_text_workflow({'novel_id': project.id}, 'story')
    params.update(output_contract=scene_prompt_batch_contract([first.id, second.id]),
        creative_method=scene_prompt_batch_method(params['creative_method']))
    task = await AiTask.create(task_type=7, status=2, request_params=params)
    conversation = await AgentConversation.create(novel=project)
    message = await AgentMessage.create(task=task, conversation=conversation, role='assistant', request_id=uuid4(), request_hash='edit')
    execution = SkillExecution({**params, 'task_id': str(task.id)}, message, AsyncMock())
    requests = mock_model(monkeypatch, {'prompts': {str(first.id): first.prompt, str(second.id): second.prompt}, 'reply': '已核对两章背景。'})
    await execution.generate_strict({'targets': [{'id': first.id}, {'id': second.id}], 'user_request': '保持各自年代修改镜头'})
    body = json.loads(requests[0]['messages'][-1]['content'])
    contexts = body['task_context']['input']['story_memory']['contexts']
    assert contexts[0]['applies_to'] == [first.id] and contexts[1]['applies_to'] == [second.id]
    assert '灾变后' not in json.dumps(contexts[0], ensure_ascii=False)
    assert '灾变后' in json.dumps(contexts[1], ensure_ascii=False)
    assert '周将军' not in json.dumps(contexts, ensure_ascii=False)
    await task.refresh_from_db()
    assert len(task.request_params['story_memory_bindings']) == 2
    await chapter_controller.patch(chapters[1].id, ChapterPatch(screenplay='后章再次修改。'))
    with pytest.raises(HTTPException):
        await verify_bindings(execution.params)


@pytest.mark.asyncio
async def test_read_tool_is_scoped_paged_and_does_not_approve_memory(story):
    project, chapters, _, _ = story
    service = SimpleNamespace(novel_id=project.id, authorization_check=AsyncMock())
    ctx = SimpleNamespace(deps=SimpleNamespace(changes=None, service=service))
    result = await read_story_memory(ctx, chapters[0].id, query='老周')
    assert result['facts'] and result['next_page'] is None
    assert '周将军' not in json.dumps(result, ensure_ascii=False)
    other = await Novel.create(name='其他作品')
    foreign = await Chapter.create(novel=other, number=1, name='其他集', content='未来世界。')
    with pytest.raises(ValueError):
        await read_story_memory(ctx, foreign.id)


@pytest.mark.asyncio
async def test_conversation_reloads_confirmed_memory_and_exposes_review_needed_after_an_edit(story):
    from services.creation_agent.project_facts import load_project_facts
    project, chapters, _, _ = story
    authorize = AsyncMock()
    before, _ = await load_project_facts(novel_id=project.id, chapter_id=chapters[0].id,
        page_size=10, character_budget=4000, authorize=authorize)
    assert before['story_memory']['enabled'] and before['story_memory']['facts']
    assert '周将军' not in json.dumps(before['story_memory'], ensure_ascii=False)
    await chapter_controller.patch(chapters[0].id, ChapterPatch(screenplay='已经修改的导演稿。'))
    after, _ = await load_project_facts(novel_id=project.id, chapter_id=chapters[0].id,
        page_size=10, character_budget=4000, authorize=authorize)
    assert after['story_memory']['state'] == 'needs_review'
    assert 'facts' not in after['story_memory']
    assert authorize.await_count == 2


@pytest.mark.asyncio
async def test_memory_endpoints_and_legacy_analysis_do_not_mix_task_results(story):
    project, chapters, _, _ = story
    old = await AiTask.create(task_type=5, status=3, request_params={'novel_id': project.id}, response_data={'story_outline': '旧速览'})
    memory = await AiTask.create(task_type=5, status=2, request_params={'novel_id': project.id, 'operation': 'story_memory_recheck'})
    assert (await novel_controller.latest_analysis(project.id)).id == old.id
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = f'/novel/{project.id}/story-memory'
        result = await client.get(url + f'/context?chapter_id={chapters[0].id}')
        assert result.status_code == 200 and result.json()['data']['enabled']
        activity = (await client.get(url + '/activity')).json()['data']
        assert activity['id'] == str(memory.id) and 'request_params' not in activity


def test_story_memory_rules_and_skill_mount_are_available_in_both_languages():
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    from services.creation_agent.deep_execution import skill_files
    from prompts.text_tasks import render_text_task
    files = skill_files(SkillSnapshot.model_validate(snapshot_skills()))
    assert '/skills/novelvids-story/SKILL.md' in files
    assert '/skills/novelvids-story/references/story_memory.md' in files
    for language in ('zh', 'en'):
        instructions, _ = render_text_task(language=language, skill={'instructions': '分析方法', 'references': []},
            context={'input': {'story_memory': {'enabled': True}}})
        assert f'language={language}' in instructions and '计划、证言、推测不当作已发生事实' in instructions
        assert '已换下、脱去、交出或损毁的服装与道具不得从基础资产重新叠加' in instructions
