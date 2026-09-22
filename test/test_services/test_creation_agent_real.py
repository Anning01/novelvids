"""Real provider proof using test overrides or user-configured process/.env values."""

import pytest

from openai import AsyncOpenAI
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from schemas.creation_agent import AgentTarget
from services.creation_agent.changes import CreationChanges
from services.creation_agent.model_usage import UsagePreservingChatModel
from services.creation_agent.runtime import CreationAgentDeps, creation_agent
from services.creation_agent.tools import PromptEditService, prompt_version
from test.test_services.test_creation_agent_crud import crud
from test.test_services.test_creation_agent_tools import setup_service
from test.creation_agent_evaluation_budget import real_evaluation_configuration, BudgetedEvaluationModel


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_real_agent_calls_scoped_storyboard_tool(test_env):
    configured = real_evaluation_configuration(test_env)
    if configured is None:
        pytest.skip('test/.test.env 或进程环境/.env 未配置 CREATION_AGENT_* 参数')
    settings, ledger, _ = configured
    service, scene, _, _, _ = await setup_service()
    service.allowed_targets = frozenset({('scene', scene.id)})
    model = UsagePreservingChatModel(settings['model'], provider=OpenAIProvider(openai_client=AsyncOpenAI(
        base_url=settings['base_url'], api_key=settings['api_key'], max_retries=0, timeout=90)))
    try:
        result = await creation_agent.run(
            '把当前分镜改成压抑的雨夜氛围，直接保存。不要改变时长、素材或分镜顺序。',
            model=BudgetedEvaluationModel(model, ledger), model_settings={'max_tokens': 3000}, deps=CreationAgentDeps(service=service, context={
                'targets': [{'kind': 'scene', 'id': scene.id, 'version': prompt_version(scene)}],
            }), usage_limits=UsageLimits(request_limit=4, tool_calls_limit=3, total_tokens_limit=12000),
        )
    finally:
        await model.client.close()
    await scene.refresh_from_db()
    assert scene.prompt != '空站台'
    assert scene.sequence == 5 and scene.duration == 6 and scene.metadata == {'keep': 'metadata'}
    assert '同上' not in scene.prompt and '镜头1的女生' not in scene.prompt
    assert result.usage().requests <= 4


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_real_progressive_agent_uses_bounded_patch_flow(test_env):
    configured = real_evaluation_configuration(test_env)
    if configured is None:
        pytest.skip('test/.test.env 或进程环境/.env 未配置 CREATION_AGENT_* 参数')
    settings, ledger, _ = configured
    original_changes, scene, _, _, task = await crud()
    selected_request = original_changes.request.model_copy(
        update={'targets': [AgentTarget(kind='scene', id=scene.id)]},
    )
    changes = CreationChanges(
        novel_id=original_changes.novel_id,
        task_id=task.id,
        request=selected_request,
        max_batch_size=8,
    )
    legacy = PromptEditService(
        novel_id=changes.novel_id,
        task_id=task.id,
        allowed_targets=set(),
        max_batch_size=8,
    )
    model = UsagePreservingChatModel(
        settings['model'],
        provider=OpenAIProvider(openai_client=AsyncOpenAI(
            base_url=settings['base_url'],
            api_key=settings['api_key'],
            max_retries=0,
            timeout=90,
        )),
    )
    try:
        result = await creation_agent.run(
            '把当前分镜提示词中唯一的“空站台”替换为“压抑的雨夜站台”，其他内容不变，直接保存。',
            model=BudgetedEvaluationModel(model, ledger),
            model_settings={'max_tokens': 1200},
            deps=CreationAgentDeps(
                service=legacy,
                changes=changes,
                context={'project': {'name': '测试项目'}, 'chapter': {'name': '测试章节'}},
            ),
            usage_limits=UsageLimits(request_limit=4, tool_calls_limit=4, total_tokens_limit=12_000),
        )
    finally:
        await model.client.close()

    await scene.refresh_from_db()
    assert '压抑的雨夜站台' in scene.prompt
    assert result.usage().requests <= 4


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_real_handler_persists_patch_and_usage_through_production_path(test_env, monkeypatch):
    """Include admission, history, stream, budget controller, write and billing."""
    import json
    from auth.deps import AuthContext
    from models.creation_agent import AgentMessage
    from models.scene import Scene
    from models.usage_record import ModelUsageRecord
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent import handler
    from services.creation_agent.sessions import agent_sessions
    from test.test_services.test_creation_agent_sessions import session_fixture
    from utils.enums import AiTaskTypeEnum, TaskStatusEnum

    configured = real_evaluation_configuration(test_env)
    if configured is None:
        pytest.skip('未配置真实模型验收参数')
    settings, ledger, _ = configured
    conversation, request, config = await session_fixture()
    config.pricing = settings['pricing']
    config.max_tokens = 1200
    await config.save()
    request = request.model_copy(update={
        'write_scope': 'selected',
        'message': '把当前分镜提示词中唯一的“空站台”替换为“压抑的雨夜站台”，其他内容不变，直接保存。',
    })
    model = UsagePreservingChatModel(settings['model'], provider=OpenAIProvider(openai_client=AsyncOpenAI(
        base_url=settings['base_url'], api_key=settings['api_key'], max_retries=0, timeout=60)))
    monkeypatch.setattr(handler, 'configured_model', lambda *args: BudgetedEvaluationModel(model, ledger))
    task = await agent_sessions.submit(conversation, request, AuthContext())
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, handler.CreationAgentTaskHandler())
    try:
        await executor.run(task)
    finally:
        await model.client.close()
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value, task.error_message
    scene = await Scene.get(id=request.targets[0].id)
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert '压抑的雨夜站台' in scene.prompt
    assert assistant.usage['requests'] <= 4
    assert all(call['context']['total_characters'] <= 64000 for call in assistant.usage['calls'])
    record = await ModelUsageRecord.get(id=assistant.billing_record_id)
    assert record.usage['cache_read_tokens'] == assistant.usage['cache_read_tokens']
    print(json.dumps({'case': 'production_patch', 'requests': assistant.usage['requests'],
        'input_tokens': assistant.usage['input_tokens'], 'output_tokens': assistant.usage['output_tokens'],
        'cache_read_tokens': assistant.usage['cache_read_tokens'], 'cost_cny': str(record.cost),
        'compactions': assistant.usage['compactions']}, ensure_ascii=False))
