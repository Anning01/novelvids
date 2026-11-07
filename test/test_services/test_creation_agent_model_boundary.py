"""Summary-phase compression calls must not spend the main loop's request budget."""

from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from services.creation_agent.model_boundary import RecordedAgentModel
from services.creation_agent.runtime import CreationAgentDeps, creation_agent
from services.creation_agent.tools import PromptEditService
from test.test_services.test_creation_agent_crud import crud


async def _allowed():
    return None


def _recorded(model, *, request_limit):
    return RecordedAgentModel(FunctionModel(model), message=SimpleNamespace(id=99_999_998, usage={}),
                              before_request=_allowed, max_characters=64_000,
                              request_limit=request_limit, total_tokens_limit=100_000)


async def _summary_call(recorded):
    previous = recorded.phase
    recorded.phase = 'summary'
    try:
        await recorded.request([ModelRequest(parts=[UserPromptPart('压缩历史')])], None, ModelRequestParameters())
    finally:
        recorded.phase = previous


@pytest.mark.asyncio
async def test_summary_phase_call_does_not_consume_main_request_limit():
    def model(messages, info):
        return ModelResponse(parts=[TextPart('ok')])

    recorded = _recorded(model, request_limit=2)
    await _summary_call(recorded)
    messages = [ModelRequest(parts=[UserPromptPart('主循环')])]
    await recorded.request(messages, None, ModelRequestParameters())
    # The second main-loop request is still within request_limit=2; only the
    # summary call precedes it and that call must not count.
    await recorded.request(messages, None, ModelRequestParameters())

    phases = [call['phase'] for call in recorded.calls]
    assert phases == ['summary', 'main', 'main']
    with pytest.raises(ValueError, match='本轮模型调用次数已达到配置上限'):
        await recorded.request(messages, None, ModelRequestParameters())


@pytest.mark.asyncio
async def test_summary_phase_call_does_not_trigger_early_final_reply_tool_removal():
    changes, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    seen_tools = []

    def model(messages, info):
        # The shared RecordedAgentModel also serves the summary request; only
        # main-loop requests carry the agent's user prompt.
        if any(isinstance(part, UserPromptPart) and part.content == '压缩历史'
               for message in messages for part in message.parts):
            return ModelResponse(parts=[TextPart('历史摘要')])
        seen_tools.append(sorted(tool.name for tool in info.function_tools))
        if len(seen_tools) == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='context')])
        return ModelResponse(parts=[TextPart('已读取当前上下文。')])

    recorded = _recorded(model, request_limit=3)
    await _summary_call(recorded)
    result = await creation_agent.run('读取上下文', model=recorded,
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}),
        usage_limits=UsageLimits(request_limit=3))

    assert result.output == '已读取当前上下文。'
    # With request_limit=3 the tools are withdrawn only on the third main
    # request. The summary call must not make the second request tool-less.
    assert len(seen_tools) == 2
    assert seen_tools[1], 'tools were withdrawn one request early because the summary call was counted'


@pytest.mark.asyncio
@pytest.mark.parametrize('with_skill_snapshot', [False, True])
async def test_final_request_withdraws_tools_and_tells_the_model_to_reply_directly(with_skill_snapshot):
    from prompts.skill_pack import snapshot_skills
    from services.creation_agent.skill_execution import SkillExecution, current_execution

    changes, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    steps = []

    def model(messages, info):
        steps.append((len(info.function_tools), info.instructions or ''))
        if len(steps) == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='context')])
        return ModelResponse(parts=[TextPart('已读取上下文，未做修改。')])

    deps = CreationAgentDeps(service=legacy, changes=changes, context={})
    token = None
    if with_skill_snapshot:
        token = current_execution.set(SkillExecution(
            {'skill_snapshot': snapshot_skills(), 'prompt_language': 'zh'}, None, _allowed))
    try:
        result = await creation_agent.run('读取上下文', model=_recorded(model, request_limit=2),
            deps=deps, usage_limits=UsageLimits(request_limit=2))
    finally:
        if token is not None:
            current_execution.reset(token)

    assert result.output == '已读取上下文，未做修改。'
    first_tools, first_instructions = steps[0]
    final_tools, final_instructions = steps[1]
    assert first_tools > 0 and '工具已收起' not in first_instructions
    assert final_tools == 0
    assert '工具已收起' in final_instructions and '最终回复' in final_instructions
    assert deps.turn_limited is True


async def _parent_execution_with_usage(calls, *, request_limit):
    """A running parent run whose persisted usage already holds the given calls."""
    from unittest.mock import AsyncMock
    from models.ai_task import AiTask
    from schemas.creation_agent import AgentConfiguration
    from services.creation_agent.production import conversation_for_task
    from services.creation_agent.skill_execution import SkillExecution, prepare_workflow
    from test.test_services.test_skill_workflow import enabled_project

    novel, _, _ = await enabled_project()
    workflow = await prepare_workflow({'novel_id': novel.id, 'prompt_language': 'zh'})
    workflow['agent_configuration'] = AgentConfiguration(enabled=True, request_limit=request_limit).model_dump()
    task = await AiTask.create(task_type=7, status=2, request_params=workflow)
    assistant = await conversation_for_task(task)
    assistant.usage = {'calls': calls, 'requests': len(calls), 'input_tokens': 0, 'output_tokens': 0}
    await assistant.save(update_fields=['usage'])
    return SkillExecution({**workflow, 'task_id': str(task.id)}, assistant, AsyncMock())


def _structured_prompt_model(text):
    from unittest.mock import AsyncMock

    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'prompt': text})])

    model = FunctionModel(respond)
    model.client = AsyncMock()
    return model


@pytest.mark.asyncio
async def test_task_total_cap_ignores_summary_phase_calls_of_the_parent_run():
    from unittest.mock import patch
    from schemas.agent_workflow import CompletePrompt

    execution = await _parent_execution_with_usage(
        [{'phase': 'main'}, {'phase': 'main'}, {'phase': 'summary'}], request_limit=3)
    with patch('services.creation_agent.handler.configured_model', return_value=_structured_prompt_model('完整提示词')):
        result = await execution.generate('image', {'description': '测试'}, CompletePrompt)
    assert result.prompt == '完整提示词'


@pytest.mark.asyncio
async def test_historical_task_total_cap_no_longer_blocks_progress():
    from unittest.mock import patch
    from schemas.agent_workflow import CompletePrompt

    execution = await _parent_execution_with_usage(
        [{'phase': 'main'}, {'phase': 'main'}, {'phase': 'main'}], request_limit=3)
    with patch('services.creation_agent.handler.configured_model', return_value=_structured_prompt_model('完整提示词')):
        result = await execution.generate('image', {'description': '测试'}, CompletePrompt)
    assert result.prompt == '完整提示词'
    await execution.message.refresh_from_db()
    assert execution.message.usage['requests'] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('reply', [
    '第 1 章的 场景 2 已调暖光线，其他人物画面未改。',
    'Scene 2 lighting is warmer now; no other shot changed.',
])
async def test_user_visible_noun_with_number_is_a_valid_final_reply(reply):
    changes, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[TextPart(reply)])

    result = await creation_agent.run('把光线调暖', model=FunctionModel(model),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}), usage_limits=UsageLimits(request_limit=3))
    assert result.output == reply
    assert calls == 1, 'a user-visible noun followed by a number must not trigger a retry'


@pytest.mark.asyncio
async def test_internal_field_names_are_still_rejected_with_actionable_copy():
    from pydantic_ai.messages import RetryPromptPart

    changes, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[TextPart('已更新 asset_id 7 的画面。')])
        retry = next(part for message in messages for part in message.parts if isinstance(part, RetryPromptPart))
        assert '用户可见的对象名称' in str(retry.content)
        assert 'asset_id' not in str(retry.content)
        return ModelResponse(parts=[TextPart('已更新该人物的画面。')])

    result = await creation_agent.run('把光线调暖', model=FunctionModel(model),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}), usage_limits=UsageLimits(request_limit=3))
    assert calls == 2
    assert result.output == '已更新该人物的画面。'
