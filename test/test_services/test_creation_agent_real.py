"""Real provider proof using test overrides or user-configured process/.env values."""

import pytest

from openai import AsyncOpenAI
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from services.creation_agent.model_usage import UsagePreservingChatModel
from services.creation_agent.runtime import CreationAgentDeps, creation_agent
from services.creation_agent.tools import prompt_version
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
