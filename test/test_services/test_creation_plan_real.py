"""Synthetic cross-chapter planning against the configured real model, never media."""

import json

import pytest

from models.chapter import Chapter
from models.config import AiModelConfig
from services.creation_agent import handler
from services.creation_agent.plans import CreationPlanner
from test.creation_agent_evaluation_budget import real_evaluation_configuration, BudgetedEvaluationModel
from test.test_services.test_creation_plans import plan_fixture


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_real_plan_reads_ten_chapters_and_hands_off_original_climax(test_env, monkeypatch):
    settings = real_evaluation_configuration(test_env)
    assert settings is not None, '真实验收配置不完整，不能把未执行报告为通过'
    configured, ledger, output = settings
    _, request, chapters, _, source, execution = await plan_fixture()
    request = request.model_copy(update={'message': '生成第一章分镜。完整阅读第一到第十章，选最强冲突倒叙开场，再切回第一章收到来信；不生成图片和视频。'})
    source.content = request.message
    source.run_input = request.model_dump(mode='json')
    await source.save(update_fields=['content', 'run_input'])
    await Chapter.filter(id=chapters[0].id).update(content='主角在清晨收到一封求救信，决定出城寻找同伴。')
    await AiModelConfig.filter(id=execution.params['assistant_model_config_id']).update(
        base_url=configured['base_url'], api_key=configured['api_key'], model=configured['model'],
        pricing=configured['pricing'], thinking=configured['thinking'])
    original = handler.configured_model
    clients = []

    def guarded(chosen, limits):
        model = original(chosen, limits)
        clients.append(model.client)
        return BudgetedEvaluationModel(model, ledger)

    monkeypatch.setattr(handler, 'configured_model', guarded)
    try:
        plan = await CreationPlanner(execution, source).prepare(request)
        assert plan is not None
        assert {c.number for c in plan.chapters} == set(range(1, 11))
        assert all(c.pages for c in plan.chapters)
        assert all(step.operation in {'assets', 'storyboard'} for step in plan.steps)
        assert any(excerpt.chapter_id == chapters[7].id and excerpt.text in chapters[7].content for excerpt in plan.excerpts)
        with (output / 'creation-plans.jsonl').open('a', encoding='utf-8') as report:
            report.write(json.dumps({'plan': plan.model_dump(mode='json'), 'quality_review': None}, ensure_ascii=False) + '\n')
    finally:
        for client in clients:
            await client.close()
