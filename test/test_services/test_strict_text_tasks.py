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
    from services.chapter_screenplay import EpisodeScript
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
    monkeypatch.setattr(EpisodeScript, 'model_validate', Mock(side_effect=AssertionError('no output revalidation')))
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
