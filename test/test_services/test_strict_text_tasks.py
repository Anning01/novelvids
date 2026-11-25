import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import AsyncOpenAI

from auth.deps import AuthContext
from models.ai_task import AiTask
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from services.ai_task_executor import ai_task_executor
from services.chapter_screenplay import submit_screenplay
from services.creation_agent.skill_execution import SkillExecution
from test.agent_stream_fixtures import completion_stream_response


@pytest.fixture(autouse=True)
def local_workspace(monkeypatch):
    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)


@pytest.fixture
async def strict_model():
    return await AiModelConfig.create(name='strict-text', model='strict-model', task_type=7,
        base_url='https://model.invalid/v1', api_key='test', is_active=True,
        supports_json_output=True, supports_strict_output=True, supports_tool_calls=False)


def mock_model(monkeypatch, payload, *, finish_reason='stop', refusal=None):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        if request.url.path.endswith('/responses'):
            result = {'id': 'resp-test', 'object': 'response', 'created_at': 1, 'model': 'strict-model',
                'status': 'completed', 'output': [],
                'usage': {'input_tokens': 24, 'output_tokens': 12, 'total_tokens': 36,
                    'input_tokens_details': {'cached_tokens': 4}, 'output_tokens_details': {'reasoning_tokens': 2}}}
            item = {'id': 'msg-test', 'type': 'message', 'role': 'assistant', 'status': 'in_progress', 'content': []}
            if not requests[-1].get('stream'):
                result['output'] = [{**item, 'status': 'completed', 'content': [
                    {'type': 'output_text', 'text': json.dumps(payload, ensure_ascii=False), 'annotations': []}]}]
                return httpx.Response(200, json=result)
            events = [
                {'type': 'response.created', 'response': {**result, 'status': 'in_progress', 'usage': None}},
                {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                {'type': 'response.content_part.added', 'item_id': item['id'], 'output_index': 0, 'content_index': 0,
                    'part': {'type': 'output_text', 'text': '', 'annotations': []}},
                {'type': 'response.output_text.delta', 'item_id': item['id'], 'output_index': 0, 'content_index': 0,
                    'delta': json.dumps(payload, ensure_ascii=False)},
                {'type': 'response.completed', 'response': result}]
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=''.join(
                'data: ' + json.dumps({**event, 'sequence_number': index}) + '\n\n' for index, event in enumerate(events)))
        return completion_stream_response({'id': 'strict', 'created': 1, 'model': 'strict-model',
            'object': 'chat.completion', 'choices': [{'index': 0, 'message': {
                'role': 'assistant', 'content': json.dumps(payload, ensure_ascii=False) if refusal is None else None,
                **({'refusal': refusal} if refusal else {})}, 'finish_reason': finish_reason}],
            'usage': {'prompt_tokens': 24, 'completion_tokens': 12, 'total_tokens': 36}})
    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['story', 'screenplay'])
@pytest.mark.parametrize('text_api', ['chat_completions', 'responses'])
@pytest.mark.parametrize('strict,json_mode', [(True, True), (True, False)])
async def test_strict_generation_has_one_request_and_no_agent_validation(strict_model, monkeypatch, operation, strict, json_mode, text_api):
    from controllers.novel import novel_controller
    from models.agent_operation import AgentOperation
    strict_model.text_api = text_api
    strict_model.supports_strict_output = strict
    strict_model.supports_json_output = json_mode
    await strict_model.save()
    novel = await Novel.create(name='渡口', content='船工守着渡口。', episodes_managed=True)
    chapter = await Chapter.create(novel=novel, number=1, name='渡口', content='船工守着渡口。')
    payload = ({'book_types': ['悬疑'], 'story_outline': '船工发现秘密。', 'key_characters': []}
               if operation == 'story' else {'screenplay': '1-1 渡口 外 夜\n△ 船工停下。'})
    requests = mock_model(monkeypatch, payload)
    legacy = AsyncMock(side_effect=AssertionError('strict tasks must not enter Agent generation'))
    monkeypatch.setattr(SkillExecution, 'generate', legacy)
    task = (await novel_controller.analyze(novel.id, include_cover=False) if operation == 'story'
            else await submit_screenplay(chapter.id, AuthContext()))
    assert 'skill_snapshot' not in task.request_params
    assert task.request_params['output_contract']['name'] == operation
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1
    output = requests[0]['text']['format'] if text_api == 'responses' else requests[0]['response_format']
    if text_api == 'responses' and strict:
        output = {'type': 'json_schema', 'json_schema': {k: v for k, v in output.items() if k != 'type'}}
    assert output == {'type': 'json_schema', 'json_schema': {
        'name': operation, 'schema': task.request_params['output_contract']['schema'], 'strict': True}}
    assert 'output_schema=' not in json.dumps(requests[0], ensure_ascii=False)
    assert not requests[0].get('tools')
    legacy.assert_not_awaited()
    assert not await AgentOperation.filter(task=task, key__startswith='recovery:repair').exists()
    await chapter.refresh_from_db()
    await novel.refresh_from_db()
    assert (novel.story_outline if operation == 'story' else chapter.screenplay) == payload.get('story_outline', payload.get('screenplay'))


@pytest.mark.asyncio
@pytest.mark.parametrize('text_api', ['chat_completions', 'responses'])
@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('pacing', [None, {'preset': 'fast', 'max_seconds': 75}])
async def test_screenplay_request_injects_settings_outside_skill_and_saves_result(strict_model, monkeypatch, text_api, language, pacing):
    strict_model.text_api = text_api
    await strict_model.save()
    monkeypatch.setattr('services.language.generation_language', AsyncMock(return_value=language))
    novel = await Novel.create(name='任务参数')
    chapter = await Chapter.create(novel=novel, number=1, name='渡口', content='船工守着渡口。', episode_pacing=pacing)
    text = '1-1 渡口 外 夜\n△ 船工停下。'
    requests = mock_model(monkeypatch, {'screenplay': text})
    task = await submit_screenplay(chapter.id, AuthContext())
    frozen_method = task.request_params['creative_method']['instructions']
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    await chapter.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1 and chapter.screenplay == text and chapter.content == '船工守着渡口。'
    request = requests[0]
    messages = request['input'] if text_api == 'responses' else request['messages']
    content = next(message['content'] for message in messages if message.get('role') == 'user')
    if isinstance(content, list):
        content = ''.join(part['text'] for part in content)
    payload = json.loads(content)
    assert payload['creative_method']['instructions'] == frozen_method
    assert payload['creative_method']['references'] == []
    assert '{{' not in frozen_method
    task_context = payload['task_context']
    assert task_context['input']['source_text'] == chapter.content
    assert task_context['episode_pacing'] == {'preset': 'smart', 'max_seconds': None, **(pacing or {})}
    requirements = task_context['screenplay_requirements']
    if pacing:
        header = 'Target episode duration: about 75s' if language == 'en' else '本集参考时长：约 75 秒'
        assert header in requirements and '不是硬性上限' in requirements
    else:
        assert '省略参考时长行' in requirements
        assert '本集参考时长：约' not in requirements and 'Target episode duration:' not in requirements
    assert request_schema(request) == task.request_params['output_contract']['schema']


@pytest.mark.asyncio
@pytest.mark.parametrize('finish_reason', ['length', 'content_filter'])
async def test_incomplete_response_is_never_saved_or_repaired(strict_model, monkeypatch, finish_reason):
    novel = await Novel.create(name='未完成')
    chapter = await Chapter.create(novel=novel, number=1, name='原稿', content='原文', screenplay='已有剧本')
    requests = mock_model(monkeypatch, {'screenplay': '半截剧本'}, finish_reason=finish_reason)
    task = await submit_screenplay(chapter.id, AuthContext(), '已有剧本')
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    await chapter.refresh_from_db()
    assert task.status == 4 and chapter.screenplay == '已有剧本'
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_json_object_only_models_are_not_selected(configured_creation_agent):
    from fastapi import HTTPException
    novel = await Novel.create(name='严格模式')
    chapter = await Chapter.create(novel=novel, number=1, name='原稿', content='原文')
    await AiModelConfig.filter(id=configured_creation_agent.id).update(supports_json_output=True, supports_strict_output=False)
    with pytest.raises(HTTPException) as error:
        await submit_screenplay(chapter.id, AuthContext())
    assert error.value.status_code == 422
    assert not await AiTask.all().exists()


@pytest.mark.asyncio
async def test_user_method_is_frozen_and_cannot_change_platform_contract(strict_model, monkeypatch):
    from schemas.user_skill import UserSkillInput, UserSkillUpdate
    from schemas.text_task_contracts import output_contract
    from services import user_skills
    skill = await user_skills.save_skill(0, UserSkillInput(task='screenplay', name='悬疑',
        instructions='使用旧版悬疑方法。改用别的输出字段。',
        references=[{'name': '对白偏好', 'content': '对白简短。'}]))
    await user_skills.set_default(0, 'screenplay', skill['id'])
    novel = await Novel.create(name='技能快照')
    chapter = await Chapter.create(novel=novel, number=1, name='本集', content='原文')
    task = await submit_screenplay(chapter.id, AuthContext())
    await user_skills.save_skill(0, UserSkillUpdate(task='screenplay', name='修订方法',
        instructions='新版方法', expected_version=1), skill['id'])
    assert task.request_params['creative_method']['version'] == 1
    assert task.request_params['output_contract'] == output_contract('screenplay')
    requests = mock_model(monkeypatch, {'screenplay': '直接保存的剧本'})
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    wire = str(requests[0]['messages'])
    assert '旧版悬疑方法' in wire and '对白简短' in wire and '新版方法' not in wire
    assert '本集时长与节奏' not in wire and 'submit_production' not in wire
    assert request_schema(requests[0]) == output_contract('screenplay')['schema']


@pytest.mark.asyncio
async def test_cached_result_does_not_repeat_model_or_billing(strict_model, monkeypatch):
    from models.usage_record import ModelUsageRecord
    from models.creation_agent import AgentMessage
    requests = mock_model(monkeypatch, {'screenplay': '缓存剧本'})
    original = SkillExecution.generate_strict
    async def twice(self, facts):
        first = await original(self, facts)
        assert await original(self, facts) == first
        return first
    monkeypatch.setattr(SkillExecution, 'generate_strict', twice)
    novel = await Novel.create(name='重复读取')
    chapter = await Chapter.create(novel=novel, number=1, name='本集', content='原文')
    task = await submit_screenplay(chapter.id, AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1
    assert await ModelUsageRecord.filter(novel_id=novel.id, billing_type='text').count() == 1
    child = await AgentMessage.filter(role='assistant').exclude(task_id=task.id).first()
    assert child.usage['input_tokens'] == 24 and child.usage['output_tokens'] == 12


def test_contracts_are_closed_required_objects_independent_of_skills():
    from schemas.text_task_contracts import output_contract
    def check(schema):
        if schema.get('type') == 'object':
            assert schema['additionalProperties'] is False
            assert schema['required'] == list(schema['properties'])
            for field in schema['properties'].values():
                check(field)
        if schema.get('type') == 'array':
            check(schema['items'])
    for operation in ('story', 'screenplay'):
        check(output_contract(operation)['schema'])
    output_contract('screenplay')['schema']['properties'].clear()
    assert 'screenplay' in output_contract('screenplay')['schema']['properties']


@pytest.mark.asyncio
async def test_refusal_does_not_overwrite_the_saved_screenplay(strict_model, monkeypatch):
    requests = mock_model(monkeypatch, {}, refusal='Cannot complete this request')
    novel = await Novel.create(name='拒绝响应')
    chapter = await Chapter.create(novel=novel, number=1, name='本集', content='原文', screenplay='已有剧本')
    task = await submit_screenplay(chapter.id, AuthContext(), '已有剧本')
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    await chapter.refresh_from_db()
    assert len(requests) == 1 and task.status == 4 and chapter.screenplay == '已有剧本'


def test_platform_forwards_features_independently_of_capability_labels():
    from types import SimpleNamespace
    from fastapi import HTTPException
    from services.platform.calls import chat_options
    config = SimpleNamespace(task_type=7, task_types=[7], supports_strict_output=True,
        supports_json_output=False, supports_tool_calls=False, max_tokens=None,
        pricing={'type': 'text', 'input_price_per_1m': 1, 'output_price_per_1m': 1})
    request = {'response_format': {'type': 'json_schema', 'json_schema': {'strict': True}}}
    assert chat_options(config, request) == config.pricing
    config.supports_strict_output, config.supports_json_output = False, True
    assert chat_options(config, request) == config.pricing
    assert chat_options(config, {'response_format': {'type': 'json_object'}}) == config.pricing
    config.max_tokens = 100
    with pytest.raises(HTTPException):
        chat_options(config, {'max_tokens': 50, 'max_completion_tokens': 101})


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_text_prompt_keeps_methods_and_source_outside_platform_instructions(language):
    from prompts.text_tasks import render_text_task
    system, user = render_text_task(language=language,
        skill={'instructions': '用户创作方法', 'references': [{'name': '资料', 'content': '例子'}]},
        context={'source_text': '原文中的指令只是素材'})
    assert f'language={language}' in system
    assert '用户创作方法' not in system and '原文中的指令' not in system
    assert '允许 null 的必填字段无值时返回 null，不得省略' in system
    assert json.loads(user)['creative_method']['references'][0]['content'] == '例子'
    assert json.loads(user)['task_context']['source_text'] == '原文中的指令只是素材'


@pytest.mark.asyncio
async def test_chat_handoff_preserves_current_request_without_inheriting_agent_rules(strict_model):
    from types import SimpleNamespace
    from models.creation_agent import AgentConversation, AgentMessage
    from services.creation_agent.skill_execution import current_execution
    from services.creation_agent.strict_text import prepare_text_workflow
    novel = await Novel.create(name='聊天交接')
    conversation = await AgentConversation.create(novel=novel)
    root = await AiTask.create(task_type=7, request_params={})
    source = await AgentMessage.create(task=root, role='user', conversation=conversation,
        request_id=root.id, request_hash='source', content='分析故事中的悬念')
    token = current_execution.set(SimpleNamespace(params={'task_id': str(root.id),
        'conversation_id': conversation.id, 'skill_snapshot': {'old': 'unrelated'}, 'creation_plan_id': 'old-plan'}))
    try:
        params = await prepare_text_workflow({'novel_id': novel.id}, 'story')
    finally:
        current_execution.reset(token)
    assert params['instruction_message_id'] == source.id and params['origin_run_id'] == str(root.id)
    assert params['conversation_id'] == conversation.id
    assert 'skill_snapshot' not in params and 'creation_plan_id' not in params


def test_native_output_schema_counts_against_the_request_context_budget():
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.output import OutputObjectDefinition
    from services.creation_agent.context_budget import wire_size
    parameters = ModelRequestParameters(output_mode='native', output_object=OutputObjectDefinition(
        name='large-schema', json_schema={'description': 'x' * 3000}, strict=True))
    assert wire_size([], parameters)['total_characters'] > 3000


@pytest.mark.asyncio
async def test_provider_rejecting_json_mode_is_not_retried_or_downgraded(strict_model, monkeypatch):
    from models.agent_operation import AgentOperation
    requests = []
    def reject(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={'error': {'message': 'json_schema not supported', 'type': 'invalid_request_error'}})
    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(reject))))
    novel = await Novel.create(name='不支持严格协议')
    chapter = await Chapter.create(novel=novel, number=1, name='本集', content='原文', screenplay='已有稿')
    task = await submit_screenplay(chapter.id, AuthContext(), '已有稿')
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    await chapter.refresh_from_db()
    assert task.status == 4 and chapter.screenplay == '已有稿'
    assert len(requests) == 1 and requests[0]['response_format']['type'] == 'json_schema'
    receipt = await AgentOperation.get(task=task, key='model:strict:screenplay')
    assert receipt.state == 'failed' and task.stage != 'needs_review'


def request_schema(request):
    if 'text' in request:
        return request['text']['format']['schema']
    return request['response_format']['json_schema']['schema']


@pytest.mark.asyncio
@pytest.mark.parametrize('text_api,finish_reason', [
    ('chat_completions', 'stop'), ('responses', 'stop'), ('chat_completions', 'length')])
async def test_chat_scene_edit_uses_one_strict_request(strict_model, monkeypatch, text_api, finish_reason):
    from models.creation_agent import AgentConversation, AgentMessage, PromptChange
    from schemas.creation_agent import AgentConfiguration, AgentTarget
    from services.creation_agent.object_drafts import revise_object
    from test.test_services.test_creation_agent_crud import crud
    service, scene, _, _, task = await crud()
    strict_model.text_api = text_api
    await strict_model.save()
    conversation = await AgentConversation.create(novel_id=service.novel_id)
    message = await AgentMessage.create(conversation=conversation, task=task, role='assistant',
        request_id=task.id, request_hash=str(task.id))
    params = {'task_id': str(task.id), 'novel_id': service.novel_id,
        'assistant_model_config_id': strict_model.id, 'prompt_language': 'zh',
        'agent_configuration': AgentConfiguration().model_dump()}
    requests = mock_model(monkeypatch, {'prompt': '暖色调。\n暖色调。'}, finish_reason=finish_reason)
    execution = SkillExecution(params, message, AsyncMock())
    target = AgentTarget(kind='scene', id=scene.id)
    if finish_reason == 'length' and text_api == 'chat_completions':
        with pytest.raises(ValueError, match='未完整'):
            await revise_object(service, execution, target, '暖色调', 'edit')
        assert not await PromptChange.filter(task=task).exists()
    else:
        await revise_object(service, execution, target, '暖色调', 'edit')
        await scene.refresh_from_db()
        assert scene.prompt == '暖色调。\n暖色调。'
    assert len(requests) == 1
    request = requests[0]
    assert not request.get('tools')
    fmt = request['text']['format'] if text_api == 'responses' else request['response_format']['json_schema']
    assert fmt['strict'] is True and fmt['schema']['required'] == ['prompt']
    assert '空站台' in json.dumps(request, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(('language', 'screenplay'), [('zh', '1-1 内 木屋 日\n老周开门接信。'), ('en', None)])
async def test_storyboard_sends_one_narrative_source_and_scene_grouping_rules(strict_model, monkeypatch, language, screenplay):
    from controllers.scene import scene_controller
    from test.test_services.test_prompt_language import _shot

    monkeypatch.setattr('controllers.scene.general_config_controller.get_prompt_language', AsyncMock(return_value=language))
    project = await Novel.create(name='山居')
    original = '小说独有情节：老周下山赶集。'
    chapter = await Chapter.create(novel=project, number=1, name='送信', content=original, screenplay=screenplay)
    shot = _shot().model_dump(exclude={'prompt', 'sequence', 'reference_only_types'})
    shot.update(duration=4, visible_asset_names=[], actions=[{'start': 0, 'end': 4, 'text': '开门'}],
               visual_prose='木屋门开了。', dialogue=[], narration=[], blocking_map=None)
    requests = mock_model(monkeypatch, {'shots': [shot]})
    task = await scene_controller.generate(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1
    system, user = requests[0]['messages']
    assert f'language={language}' in system['content']
    body = json.loads(user['content'])
    assert body['task_context']['input']['chapter'] == (screenplay or original)
    if screenplay:
        assert original not in user['content']
    from prompts.text_tasks import builtin_method
    method = body['creative_method']
    assert method['instructions'] == builtin_method('storyboard')['instructions']
    rules = {ref['name']: ref['content'] for ref in method['references']}
    assert '相邻两段的 duration 之和' in rules['references/continuity.md']
    assert '并入同一个 shot' in rules['references/continuity.md']
    assert '故事记忆只用于接戏' in rules['references/storyboard.md']
    assert '段尾 transition' in rules['references/storyboard.md']
    assert 'references/blocking.md' not in rules
    assert 'references/runtime-method.md' not in rules
    fields = requests[0]['response_format']['json_schema']['schema']['properties']['shots']['items']['properties']
    assert '观看重点' in fields['segments']['description']
    assert '剪辑点' in fields['transition']['description']


@pytest.mark.asyncio
@pytest.mark.parametrize('schema_in_prompt', [False, True])
async def test_schema_reaches_the_prompt_only_when_the_gateway_ignores_strict(
    strict_model, monkeypatch, schema_in_prompt,
):
    """不执行 strict 的网关会让模型自造字段名；开关开启后字段定义随提示词下发。"""
    strict_model.schema_in_prompt = schema_in_prompt
    await strict_model.save()
    novel = await Novel.create(name='网关兜底')
    chapter = await Chapter.create(novel=novel, number=1, name='渡口', content='船工守着渡口。')
    requests = mock_model(monkeypatch, {'screenplay': '1-1 渡口 外 夜\n△ 船工停下。'})
    task = await submit_screenplay(chapter.id, AuthContext())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    serialized = json.dumps(requests[0], ensure_ascii=False)
    if schema_in_prompt:
        assert 'output_schema=' in serialized
        assert 'screenplay' in serialized
    else:
        assert 'output_schema=' not in serialized


@pytest.mark.asyncio
async def test_schema_in_prompt_off_by_default(strict_model):
    """默认关闭：既有部署升级后行为不变。"""
    assert strict_model.schema_in_prompt is False
