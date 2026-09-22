"""Opt-in provider acceptance: run with -m real_llm and --maxfail=1 after pricing review."""

import json

import pytest

from models.config import AiModelConfig
from services.creation_agent import handler
from test.creation_agent_evaluation import load_cases, run_evaluation_case
from test.creation_agent_evaluation_budget import real_evaluation_configuration, BudgetedEvaluationModel
from utils.enums import AiTaskTypeEnum


@pytest.mark.real_llm
@pytest.mark.asyncio
@pytest.mark.parametrize('case', load_cases(), ids=lambda case: case.id)
@pytest.mark.parametrize('repetition', [1, 2, 3])
async def test_real_creation_agent_fixed_case(case, repetition, test_env, monkeypatch):
    settings = real_evaluation_configuration(test_env)
    if settings is None:
        pytest.skip('test/.test.env 或根 .env 尚未配置 CREATION_AGENT_*')
    configured, ledger, output = settings
    config = await AiModelConfig.create(task_type=AiTaskTypeEnum.creation_agent.value, name='真实验收', model=configured['model'],
        base_url=configured['base_url'], api_key=configured['api_key'], supports_tool_calls=True, is_active=True,
        pricing=configured['pricing'], thinking=configured['thinking'])
    clients = []
    factory = handler.configured_model

    def guarded_model(chosen, limits):
        provider = factory(chosen, limits)
        clients.append(provider.client)
        return BudgetedEvaluationModel(provider, ledger)

    monkeypatch.setattr(handler, 'configured_model', guarded_model)
    try:
        result = await run_evaluation_case(case, config, repetition)
        result['pricing'] = configured['pricing']
        result['pricing_source'] = configured['pricing_source']
        result['run_id'] = configured['run_id']
        with (output / 'results.jsonl').open('a', encoding='utf-8') as report:
            report.write(json.dumps(result, ensure_ascii=False, default=str) + '\n')
        assert result['status'] not in ('hard_failure', 'outcome_failure'), (
            f"{case.id} 未通过，脱敏证据已保存到 {output / 'results.jsonl'}")
    finally:
        for client in clients:
            await client.close()
