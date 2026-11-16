"""Keep v1.9 storyboard admission while reading plans saved by newer releases."""
from unittest.mock import AsyncMock, patch

import pytest

from models.agent_operation import AgentOperation
from services.creation_agent.step_context import validate_step_inputs
from services.creation_agent.plans import load_plan
from services.storyboard.handler import StoryboardTaskHandler
from test.test_services.test_storyboard_input_versions import storyboard_plan


@pytest.mark.asyncio
async def test_new_storyboard_plans_do_not_compute_v110_design_fingerprints():
    with patch('services.creation_agent.input_versions.storyboard_input_versions',
               AsyncMock(side_effect=AssertionError('v1.10 fingerprint should not run'))):
        _, params = await storyboard_plan()
    assert (await load_plan(params['creation_plan_id'])).storyboard_input_versions == {}


@pytest.mark.asyncio
async def test_v110_saved_field_is_readable_but_does_not_replace_v19_object_versions():
    asset, params = await storyboard_plan()
    row = await AgentOperation.get(task_id=params['creation_plan_id'], key='creation:plan')
    row.result['storyboard_input_versions'] = {f'asset:{asset.id}': 'v110-saved-fingerprint'}
    await row.save(update_fields=['result'])
    await validate_step_inputs(params)
    asset.description = 'changed after planning'
    await asset.save()
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs(params)


@pytest.mark.asyncio
async def test_storyboard_entry_does_not_add_v110_preflight_before_model():
    _, params = await storyboard_plan()
    generate = AsyncMock(side_effect=RuntimeError('model-boundary-reached'))
    with patch('services.creation_agent.step_context.validate_step_inputs', AsyncMock(side_effect=ValueError('new-preflight'))), \
            patch('services.storyboard.handler.generate_storyboard', generate):
        with pytest.raises(Exception, match='model-boundary-reached'):
            await StoryboardTaskHandler().execute({**params, 'base_url': 'https://example.invalid', 'api_key': 'test', 'model': 'test'})
    generate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('task_type,expected', [(3, True), (1, False)])
async def test_strict_streaming_is_scoped_to_storyboard_production(task_type, expected):
    from types import SimpleNamespace
    from models.ai_task import AiTask
    from services.creation_agent.production import run_production
    from services.creation_agent.skill_execution import prepare_workflow, current_execution
    from test.test_services.test_skill_workflow import enabled_project
    novel, chapter, config = await enabled_project()
    params = await prepare_workflow({'novel_id': novel.id, 'chapter_id': chapter.id,
        'assistant_model_config_id': config.id, 'model_config_id': config.id})
    task = await AiTask.create(task_type=task_type, status=2, request_params=params)
    async def execute(_params):
        assert current_execution.get().strict_streaming is expected
        return {'checked': True}
    result = await run_production(task, SimpleNamespace(execute=execute))
    assert result['checked']
