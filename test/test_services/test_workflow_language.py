from unittest.mock import AsyncMock

import pytest

from models.ai_task import AiTask
from models.config import AiModelConfig, GeneralConfig
from models.scene import Scene
from models.video import Video
from models.usage_record import ModelUsageRecord
from schemas.video import VideoBatchGenerateRequest, VideoGenerateRequest
from services.creation_agent.production import conversation_for_task
from services.creation_agent.skill_execution import SkillExecution, current_execution, prepare_workflow
from services.creation_agent.waiting import WaitingForDependencies
from services.video.batches import VideoBatchHandler, submit_batch
from test.test_services.test_skill_workflow import enabled_project
from utils.prompt_language import task_language


@pytest.mark.asyncio
async def test_workflow_snapshots_configured_language_before_direct_task_creation():
    project, _, _ = await enabled_project()
    await GeneralConfig.create(id=1, prompt_language='zh')
    original = {'novel_id': project.id, 'operation': 'video_batch'}
    prepared = await prepare_workflow(original)
    assert prepared['prompt_language'] == 'zh'
    assert 'prompt_language' not in original
    assert (await prepare_workflow({**original, 'prompt_language': 'en'}))['prompt_language'] == 'en'


@pytest.mark.asyncio
async def test_legacy_workflow_missing_language_keeps_snapshot_and_uses_execution_language():
    project, _, _ = await enabled_project()
    prepared = await prepare_workflow({'novel_id': project.id, 'prompt_language': 'en'})
    prepared.pop('prompt_language')
    token = task_language.set('zh')
    try:
        recovered = await prepare_workflow(prepared)
    finally:
        task_language.reset(token)
    assert recovered['prompt_language'] == 'zh'
    assert recovered['skill_snapshot'] == prepared['skill_snapshot']
    assert recovered['assistant_model_config_id'] == prepared['assistant_model_config_id']
    assert 'prompt_language' not in prepared


@pytest.mark.asyncio
async def test_child_of_legacy_parent_uses_existing_legacy_language_contract_without_key_error():
    project, _, _ = await enabled_project()
    params = await prepare_workflow({'novel_id': project.id, 'prompt_language': 'zh'})
    params.pop('prompt_language')
    task = await AiTask.create(task_type=4, status=2, request_params=params)
    execution = SkillExecution({**params, 'task_id': str(task.id)}, await conversation_for_task(task), AsyncMock())
    token = current_execution.set(execution)
    try:
        child = await prepare_workflow({'novel_id': project.id, 'prompt_language': 'zh'})
    finally:
        current_execution.reset(token)
    assert child['prompt_language'] == execution.language == 'en'
    assert child['origin_run_id'] == str(task.id)
    assert await ModelUsageRecord.all().count() == 0


@pytest.mark.asyncio
async def test_real_batch_admission_creates_first_child_with_language_without_a_provider_call():
    project, chapter, _ = await enabled_project()
    await GeneralConfig.create(id=1, prompt_language='zh')
    config = await AiModelConfig.create(task_type=4, name='video', model='configured-model', api_key='test-key',
        base_url='https://video.example.test/api/v3', video_model_type='seedance_2',
        api_protocol='volcengine_ark', is_active=True)
    scenes = [await Scene.create(chapter=chapter, sequence=index, prompt='Shot', duration=5) for index in (1, 2)]
    request = VideoBatchGenerateRequest(requests=[VideoGenerateRequest(scene_id=scene.id,
        model_config_id=config.id, duration=5, return_last_frame=True) for scene in scenes])
    batch = await submit_batch(request)
    assert batch.request_params['prompt_language'] == 'zh'
    batch.status = 2
    await batch.save(update_fields=['status'])
    params = {**batch.request_params, 'task_id': str(batch.id)}
    execution = SkillExecution(params, await conversation_for_task(batch), AsyncMock())
    token = current_execution.set(execution)
    try:
        with pytest.raises(WaitingForDependencies):
            await VideoBatchHandler().execute(params)
    finally:
        current_execution.reset(token)
    child = await Video.get(scene=scenes[0])
    child_task = await AiTask.get(id=child.metadata['agent_run_id'])
    assert child_task.request_params['prompt_language'] == 'zh'
    assert child_task.request_params['origin_run_id'] == str(batch.id)
    assert child.external_task_id is None
    assert await Video.filter(scene=scenes[1]).count() == 0
    assert await ModelUsageRecord.all().count() == 0
