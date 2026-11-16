"""Media admission and execution must not require or occupy a chat Agent."""
from unittest.mock import AsyncMock
import asyncio

import pytest

from models.ai_task import AiTask
from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig
from models.creation_agent import AgentMessage
from models.novel import Novel
from models.scene import Scene


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)


async def media_project():
    novel = await Novel.create(name='Background media', storyboard_enabled=True)
    chapter = await Chapter.create(novel=novel, number=1, name='First', content='Story')
    image = await AiModelConfig.create(name='image', task_type=2, model='image',
        image_model_type='gpt_image_2', api_protocol='openai_compatible',
        base_url='https://example.invalid', api_key='synthetic', is_active=True)
    asset = await Asset.create(novel=novel, canonical_name='Alex', asset_type=1,
        base_traits='A complete character reference', metadata={'model_config_id': image.id})
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='A complete shot prompt',
        prompt_params={'visual_prose': 'A room', 'actions': [{'action': 'Walk'}]})
    return novel, chapter, image, asset, scene


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['image', 'cover', 'sheet'])
async def test_media_buttons_submit_without_an_assistant_model(entry):
    novel, _, model, asset, scene = await media_project()
    if entry == 'image':
        from controllers.asset import asset_controller
        task = await asset_controller.reference(asset.id)
    elif entry == 'cover':
        from controllers.novel import novel_controller
        task = await novel_controller.analyze(novel.id, cover_only=True, cover_model_config_id=model.id)
    else:
        from services.storyboard.sheets import submit_sheet
        task = await submit_sheet(scene.id, model_config_id=model.id)
    assert task.status in {1, 6}
    assert 'assistant_model_config_id' not in task.request_params
    assert 'api_key' not in task.request_params
    assert await AgentMessage.all().count() == 0


@pytest.mark.asyncio
async def test_sheet_edit_returns_before_provider_and_worker_creates_no_chat(monkeypatch):
    from test.test_services.test_storyboard_sheet_edit import fixture
    from services.storyboard.sheets import submit_sheet_edit
    from services.storyboard.sheet_history import sheet_revision
    from schemas.storyboard_sheet import SheetEditRequest
    from services.ai_task_executor import ai_task_executor
    scene, _, _, provider, _ = await fixture(monkeypatch)
    await AiModelConfig.filter(task_type=7).update(is_active=False)
    before = await AgentMessage.all().count()
    task = await submit_sheet_edit(scene.id, SheetEditRequest(instruction='调整第二格', expected_revision=sheet_revision(scene)))
    provider.assert_not_awaited()
    monkeypatch.setattr('services.ai_task_executor.record_ai_task_usage', AsyncMock())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    provider.assert_awaited_once()
    assert await AgentMessage.all().count() == before


@pytest.mark.asyncio
async def test_ordinary_video_batch_is_admitted_without_agent_or_tail_frames():
    from services.video.batches import submit_batch
    from schemas.video import VideoBatchGenerateRequest, VideoGenerateRequest
    _, chapter, _, _, scene = await media_project()
    second = await Scene.create(chapter=chapter, sequence=2, prompt='Second shot')
    task = await submit_batch(VideoBatchGenerateRequest(requests=[
        VideoGenerateRequest(scene_id=item.id, model_config_id=1, return_last_frame=False)
        for item in (scene, second)]))
    assert task.status in {1, 6}
    assert len(task.request_params['batch_requests']) == 2
    assert await AgentMessage.all().count() == 0


@pytest.mark.asyncio
async def test_plan_waiting_for_media_releases_the_conversation(monkeypatch):
    from test.test_services.test_creation_plans import confirmed_fixture
    from models.agent_operation import AgentOperation
    from services.creation_agent.plan_execution import CreationPlanRunner
    from services.creation_agent.waiting import WaitingForDependencies
    conversation, _, plan, task, execution = await confirmed_fixture()
    scene = await Scene.get(chapter_id=plan.steps[0].target_id)
    plan.steps[0].operation = 'video'
    plan.steps[0].target_id = scene.id
    plan.steps[0].sources = []
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    child = await AiTask.create(task_type=4, status=2, request_params={'execution_mode': 'media'})
    runner = CreationPlanRunner(execution)
    monkeypatch.setattr(runner, 'target', AsyncMock(return_value={'task_id': str(child.id)}))
    with pytest.raises(WaitingForDependencies):
        await runner.run()
    await conversation.refresh_from_db()
    await task.refresh_from_db()
    assert conversation.active_task_id is None
    assert task.request_params['background'] is True
    assert task.status == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['chat', 'analysis'])
async def test_slow_media_does_not_take_the_agent_execution_slot(monkeypatch, kind):
    from types import SimpleNamespace
    from services.ai_task_executor import AiTaskExecutor
    executor = AiTaskExecutor()
    entered, release, agent_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    config = await AiModelConfig.create(name='shared-image', task_type=2, model='image', api_key='synthetic', base_url='https://example.invalid', concurrency=1)
    media = await AiTask.create(task_type=2, request_params={'workflow_version': 'agent-skills-v1', 'execution_mode': 'media', 'model_config_id': config.id})
    chat = await AiTask.create(task_type=7 if kind == 'chat' else 5, request_params={'workflow_version': 'agent-skills-v1',
        **({'background_media': True, 'include_cover': True, 'cover_model_config_id': config.id} if kind == 'analysis' else {})})
    monkeypatch.setattr('services.creation_agent.sessions.agent_configuration', AsyncMock(return_value=SimpleNamespace(production_concurrency=1)))
    async def run(task):
        if task.id == media.id:
            entered.set()
            await release.wait()
        else:
            agent_done.set()
    monkeypatch.setattr(executor, '_run_once', run)
    media_run = asyncio.create_task(executor.run(media))
    await entered.wait()
    agent_run = asyncio.create_task(executor.run(chat))
    try:
        await asyncio.wait_for(agent_done.wait(), 1)
    finally:
        release.set()
        await asyncio.gather(media_run, agent_run)


@pytest.mark.asyncio
async def test_worker_rejects_changed_prompt_before_calling_image_provider(monkeypatch):
    from controllers.asset import asset_controller
    from services.ai_task_executor import ai_task_executor
    _, _, _, asset, _ = await media_project()
    task = await asset_controller.reference(asset.id)
    await Asset.filter(id=asset.id).update(base_traits='Changed after submission')
    provider = AsyncMock()
    monkeypatch.setattr('services.reference.generator.generate_images', provider)
    monkeypatch.setattr('services.ai_task_executor.record_ai_task_usage', AsyncMock())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_sheet_edit_retries_without_creating_an_agent_message(monkeypatch):
    from test.test_services.test_storyboard_sheet_edit import fixture
    from schemas.storyboard_sheet import SheetEditRequest
    from services.storyboard.sheets import submit_sheet_edit
    from services.storyboard.sheet_history import sheet_revision
    from services.media_tasks import retry_media_task
    from services.ai_task_executor import ai_task_executor
    scene, _, _, provider, _ = await fixture(monkeypatch)
    task = await submit_sheet_edit(scene.id, SheetEditRequest(instruction='调整第二格', expected_revision=sheet_revision(scene)))
    before = await AgentMessage.all().count()
    monkeypatch.setattr('services.ai_task_executor.record_ai_task_usage', AsyncMock())
    provider.side_effect = TimeoutError('provider timeout')
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4 and task.stage == 'needs_review'
    await retry_media_task(task)
    provider.side_effect = None
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert await AgentMessage.all().count() == before
    assert task.request_params['edit_instruction'] == '调整第二格'


@pytest.mark.asyncio
async def test_ordinary_batch_submits_all_children_once_and_isolates_failure(monkeypatch):
    from services.video.batches import submit_batch, VideoBatchHandler
    from services.creation_agent.waiting import WaitingForDependencies
    from schemas.video import VideoBatchGenerateRequest, VideoGenerateRequest
    from models.video import Video
    _, chapter, _, _, scene = await media_project()
    second = await Scene.create(chapter=chapter, sequence=2, prompt='Second')
    task = await submit_batch(VideoBatchGenerateRequest(requests=[VideoGenerateRequest(scene_id=s.id, model_config_id=1) for s in (scene, second)]))
    await AiTask.filter(id=task.id).update(status=2)
    async def submit(request, **kwargs):
        child = await AiTask.create(task_type=4, status=2)
        return await Video.create(scene_id=request.scene_id, model_type=1, status=2, metadata={'agent_run_id': str(child.id)})
    provider = AsyncMock(side_effect=submit)
    monkeypatch.setattr('services.creation_agent.video_jobs.submit_video', provider)
    params = {**task.request_params, 'task_id': str(task.id)}
    for _ in range(2):
        with pytest.raises(WaitingForDependencies):
            await VideoBatchHandler().execute(params)
    assert provider.await_count == 2
    await Video.filter(scene=scene).update(status=4)
    await Video.filter(scene=second).update(status=3, url='/media/done.mp4')
    result = await VideoBatchHandler().execute(params)
    assert result['completed_count'] == 1 and result['failed_count'] == 1
    assert provider.await_count == 2


@pytest.mark.asyncio
async def test_story_analysis_finishes_before_its_cover_calls_the_provider(monkeypatch):
    from controllers.novel import novel_controller
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    from services.project_analysis.handler import BookAnalysis
    from test.test_services.test_skill_workflow import enabled_project
    novel, _, _ = await enabled_project()
    await Novel.filter(id=novel.id).update(content='A story')
    image = await AiModelConfig.create(name='cover', task_type=2, model='image', image_model_type='gpt_image_2',
        base_url='https://example.invalid', api_key='synthetic', is_active=True)
    monkeypatch.setattr(SkillExecution, 'generate', AsyncMock(return_value=BookAnalysis(book_types=['Drama'], story_outline='A story', key_characters=[])))
    provider = AsyncMock()
    monkeypatch.setattr('services.project_analysis.handler.generate_images', provider)
    monkeypatch.setattr('services.ai_task_executor.record_ai_task_usage', AsyncMock())
    analysis = await novel_controller.analyze(novel.id, cover_model_config_id=image.id)
    await ai_task_executor.run(analysis)
    await analysis.refresh_from_db()
    assert analysis.status == 3, analysis.error_message
    provider.assert_not_awaited()
    cover = await AiTask.get(id=analysis.response_data['cover_task_id'])
    assert cover.request_params['execution_mode'] == 'media'
    assert not await AgentMessage.filter(task=cover).exists()
    assert (await novel_controller.meta(novel.id))['active_cover_task_id'] == str(cover.id)


@pytest.mark.asyncio
async def test_video_provider_submission_needs_no_agent_and_keeps_its_polling_receipt(monkeypatch):
    from controllers.video import video_controller
    from schemas.video import VideoGenerateRequest
    from services.ai_task_executor import ai_task_executor
    _, _, _, _, scene = await media_project()
    model = await AiModelConfig.create(name='video', model='video', task_type=4, api_key='synthetic',
        base_url='https://example.invalid', video_model_type='seedance_2', api_protocol='volcengine_ark', is_active=True)
    provider = AsyncMock(submit=AsyncMock(return_value='external-job'))
    monkeypatch.setattr('controllers.video.get_generator', lambda config: provider)
    video = await video_controller.generate(VideoGenerateRequest(scene_id=scene.id, model_config_id=model.id, duration=6))
    provider.submit.assert_not_awaited()
    task = await AiTask.get(id=video.metadata['agent_run_id'])
    await ai_task_executor.run(task)
    await video.refresh_from_db()
    await task.refresh_from_db()
    assert task.stage == 'waiting_media', task.error_message
    assert video.external_task_id == 'external-job'
    assert not await AgentMessage.all().exists()
    provider.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_finished_batch_replayed_after_lost_response_keeps_original_task():
    from uuid import uuid4
    from services.creation_agent.submissions import submission
    from services.video.batches import submit_batch
    from schemas.video import VideoBatchGenerateRequest, VideoGenerateRequest
    _, _, _, _, scene = await media_project()
    request = VideoBatchGenerateRequest(requests=[VideoGenerateRequest(scene_id=scene.id, model_config_id=1)])
    token = submission.set({'submission_id': str(uuid4()), 'submission_hash': 'same-batch'})
    try:
        task = await submit_batch(request)
        await AiTask.filter(id=task.id).update(status=3)
        assert (await submit_batch(request)).id == task.id
    finally:
        submission.reset(token)


@pytest.mark.asyncio
async def test_empty_image_prompt_fails_before_provider_without_starting_an_agent(monkeypatch):
    from controllers.asset import asset_controller
    from services.ai_task_executor import ai_task_executor
    _, _, _, asset, _ = await media_project()
    await Asset.filter(id=asset.id).update(base_traits='')
    task = await asset_controller.reference(asset.id)
    provider = AsyncMock()
    monkeypatch.setattr('services.reference.generator.generate_images', provider)
    monkeypatch.setattr('services.ai_task_executor.record_ai_task_usage', AsyncMock())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    assert 'prompt' in task.error_message.lower() or '提示词' in task.error_message
    provider.assert_not_awaited()
    assert not await AgentMessage.all().exists()


@pytest.mark.asyncio
async def test_image_worker_uses_saved_prompt_and_returns_media_usage_without_chat(monkeypatch):
    from types import SimpleNamespace
    from controllers.asset import asset_controller
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import current_execution
    _, _, _, asset, _ = await media_project()
    async def generate(**kwargs):
        assert current_execution.get() is None
        assert kwargs['prompt'] == asset.base_traits
        return [SimpleNamespace(url='https://example.invalid/image.png')]
    monkeypatch.setattr('services.reference.generator.generate_images', generate)
    monkeypatch.setattr('services.reference.handler._persist_generated_image', AsyncMock(return_value='/media/image.png'))
    monkeypatch.setattr('services.ai_task_executor.record_ai_task_usage', AsyncMock())
    task = await asset_controller.reference(asset.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert task.response_data['image_count'] == 1
    assert not await AgentMessage.all().exists()
