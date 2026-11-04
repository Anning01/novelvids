from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
import asyncio
import pytest
from auth.deps import AuthContext
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.chapter_export import ChapterExport
from models.config import AiModelConfig
from models.scene import Scene
from models.video import Video
from schemas.video_defaults import AutoEnhancement
from services.creation_agent.video_jobs import submit_video
from services.video_enhancement.automatic import KEY, AutomaticEnhancementRecovery, enhancement_snapshot
from services.video_enhancement.contract import ENHANCEMENT_PRESET
from services.video_enhancement.media import export_media, file_digest
from test.test_services.test_skill_workflow import enabled_project


async def setup_job(tmp_path, monkeypatch):
    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='Saved prompt', duration=6)
    video_config = await AiModelConfig.create(task_type=4, name='Video', model='test', api_key='test',
        base_url='https://example.test', video_model_type='seedance_2', api_protocol='volcengine_ark', is_active=True)
    config = await AiModelConfig.create(task_type=8, name='Enhancement', api_key='test', is_active=True, **ENHANCEMENT_PRESET)
    request = AutoEnhancement(model_config_id=config.id, resolution='1080p')
    from schemas.video import VideoGenerateRequest
    video = await submit_video(VideoGenerateRequest(scene_id=scene.id, model_config_id=video_config.id, auto_enhancement=request))
    task = await AiTask.get(id=video.metadata['agent_run_id'])
    task.status = 3; await task.save()
    video.status = 3; video.url = '/media/source.mp4'; await video.save()
    path = tmp_path / 'source.mp4'; path.write_bytes(b'prechecked source')
    source_task = await AiTask.create(task_type=4, status=3)
    source = await ChapterExport.create(novel_id=novel.id, chapter_id=chapter.id, source_video_id=video.id,
        task=source_task, identity_key='source', source_version='version', source_sha256=file_digest(path), source_media_ref='/media/source.mp4',
        manifest=[{'scene_id': scene.id, 'video_id': video.id, 'sequence': 1}],
        source_probe={'width': 864, 'height': 496, 'duration': '6', 'fps': '24'})
    prepare = AsyncMock(return_value=(source, source_task))
    monkeypatch.setattr('controllers.chapter_export.chapter_exports.prepare_video', prepare)
    @asynccontextmanager
    async def materialize(_ref): yield path
    monkeypatch.setattr(export_media, 'materialize', materialize)
    return video, task, config, source, prepare


@pytest.mark.asyncio
async def test_checkpoint_recovery_creates_one_enhancement_task_and_keeps_usage_separate(tmp_path, monkeypatch):
    video, parent, _, source, prepare = await setup_job(tmp_path, monkeypatch)
    worker = AutomaticEnhancementRecovery()
    operation = await AgentOperation.get(task=parent, key=KEY)
    await asyncio.gather(worker.step(operation), worker.step(operation))
    await operation.refresh_from_db()
    assert operation.result['stage'] == 'enhancing'
    assert await AiTask.filter(task_type=8).count() == 1
    assert prepare.await_count == 1
    await worker.step(operation)
    assert await AiTask.filter(task_type=8).count() == 1
    enhanced = await ChapterExport.get(id=operation.result['enhancement_export_id'])
    assert enhanced.source_video_id == video.id and enhanced.parent_export_id == source.id
    task = await AiTask.get(id=enhanced.task_id)
    assert task.request_params['config_snapshot']['id'] == enhanced.recipe['config_id']
    assert parent.request_params['auto_enhancement_snapshot']['id'] == enhanced.recipe['config_id']
    assert task.request_params['origin_run_id'] == str(parent.id)
    assert 'api_key' not in parent.request_params['auto_enhancement_snapshot']
    assert (await Video.get(id=video.id)).url == '/media/source.mp4'


@pytest.mark.asyncio
async def test_changed_price_stops_followup_without_paid_submission(tmp_path, monkeypatch):
    _, parent, config, _, prepare = await setup_job(tmp_path, monkeypatch)
    config.pricing = {**config.pricing, 'discount': 0.5}; await config.save()
    operation = await AgentOperation.get(task=parent, key=KEY)
    await AutomaticEnhancementRecovery().step(operation)
    await operation.refresh_from_db()
    assert operation.state == 'completed' and operation.result['stage'] == 'needs_confirmation'
    assert await AiTask.filter(task_type=8).count() == 0
    prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_or_generation_failure_never_starts_followup(tmp_path, monkeypatch):
    video, parent, _, _, prepare = await setup_job(tmp_path, monkeypatch)
    parent.status = 5; await parent.save()
    operation = await AgentOperation.get(task=parent, key=KEY)
    await AutomaticEnhancementRecovery().step(operation)
    await operation.refresh_from_db()
    assert operation.result['stage'] == 'cancelled'
    assert await AiTask.filter(task_type=8).count() == 0
    prepare.assert_not_awaited()
    assert (await Video.get(id=video.id)).url == '/media/source.mp4'


@pytest.mark.asyncio
async def test_actual_equal_resolution_is_skipped_without_charge(tmp_path, monkeypatch):
    _, parent, _, source, _ = await setup_job(tmp_path, monkeypatch)
    source.source_probe = {**source.source_probe, 'width': 1920, 'height': 1080}; await source.save()
    operation = await AgentOperation.get(task=parent, key=KEY)
    await AutomaticEnhancementRecovery().step(operation)
    await operation.refresh_from_db()
    assert operation.result['stage'] == 'skipped'
    assert await AiTask.filter(task_type=8).count() == 0


@pytest.mark.asyncio
async def test_restart_recovers_only_local_followup_receipts(tmp_path, monkeypatch):
    _, parent, _, _, _ = await setup_job(tmp_path, monkeypatch)
    await AgentOperation.filter(task=parent, key=KEY).update(state='running')
    external = await AgentOperation.create(task=parent, key='media:external', external=True, state='uncertain')
    await AutomaticEnhancementRecovery().start()
    assert (await AgentOperation.get(task=parent, key=KEY)).state == 'pending'
    assert (await AgentOperation.get(id=external.id)).state == 'uncertain'


@pytest.mark.asyncio
async def test_uncertain_child_is_terminal_and_never_submitted_again(tmp_path, monkeypatch):
    _, parent, _, _, _ = await setup_job(tmp_path, monkeypatch)
    worker = AutomaticEnhancementRecovery()
    operation = await AgentOperation.get(task=parent, key=KEY)
    await worker.step(operation); await operation.refresh_from_db()
    enhanced = await ChapterExport.get(id=operation.result['enhancement_export_id'])
    await AiTask.filter(id=enhanced.task_id).update(status=4, stage='needs_review')
    await worker.step(operation); await operation.refresh_from_db()
    assert operation.result['stage'] == 'needs_review' and operation.state == 'completed'
    await worker.step(operation)
    assert await AiTask.filter(task_type=8).count() == 1


@pytest.mark.asyncio
async def test_cancellation_stops_an_unsubmitted_enhancement_child(tmp_path, monkeypatch):
    _, parent, _, _, _ = await setup_job(tmp_path, monkeypatch)
    worker = AutomaticEnhancementRecovery()
    operation = await AgentOperation.get(task=parent, key=KEY)
    await worker.step(operation); await operation.refresh_from_db()
    enhanced = await ChapterExport.get(id=operation.result['enhancement_export_id'])
    parent.status = 5; await parent.save()
    await worker.step(operation); await operation.refresh_from_db()
    assert operation.result['stage'] == 'cancelled'
    assert (await AiTask.get(id=enhanced.task_id)).status == 5
    assert await AiTask.filter(task_type=8).count() == 1


@pytest.mark.asyncio
async def test_stale_configuration_version_is_rejected_before_a_video_is_reserved(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from services.video_enhancement.automatic import configuration_version
    _, parent, config, _, _ = await setup_job(tmp_path, monkeypatch)
    from schemas.video import VideoGenerateRequest
    request = VideoGenerateRequest.model_validate(parent.request_params['video_request'])
    request.auto_enhancement.config_version = configuration_version(config)
    config.pricing = {**config.pricing, 'discount': 0.5}; await config.save()
    count = await Video.all().count()
    with pytest.raises(HTTPException) as error:
        await submit_video(request)
    assert error.value.status_code == 409
    assert await Video.all().count() == count


@pytest.mark.asyncio
async def test_automatic_chain_submits_collects_selects_and_bills_exactly_once(tmp_path, monkeypatch):
    from services.ai_task_executor import ai_task_executor
    from services.video_enhancement.provider import MediaKitTask
    from services.video_enhancement.recovery import collect_export
    from models.usage_record import ModelUsageRecord
    video, parent, _, source, _ = await setup_job(tmp_path, monkeypatch)
    upload = AsyncMock(return_value='mediakit://checked-source')
    submit = AsyncMock(return_value='accepted-enhancement')
    monkeypatch.setattr('services.video_enhancement.provider.MediaKitClient.upload', upload)
    monkeypatch.setattr('services.video_enhancement.provider.MediaKitClient.submit', submit)
    monkeypatch.setattr('services.video_enhancement.provider.MediaKitClient.query', AsyncMock(return_value=MediaKitTask(
        task_id='accepted-enhancement', status='completed', result={'resolution': '1080p', 'duration': '6',
        'fps': '24', 'video_url': 'https://provider.example/hd.mp4'})))
    monkeypatch.setattr(export_media, 'save_enhanced', AsyncMock(return_value={'ref': '/media/exports/1/hd.mp4',
        'sha256': source.source_sha256, 'probe': {'width': 1920, 'height': 1080, 'duration': '6', 'fps': '24'}}))
    monkeypatch.setattr(export_media, 'store', AsyncMock())
    worker = AutomaticEnhancementRecovery()
    operation = await AgentOperation.get(task=parent, key=KEY)
    await worker.step(operation); await operation.refresh_from_db()
    enhanced = await ChapterExport.get(id=operation.result['enhancement_export_id'])
    task = await AiTask.get(id=enhanced.task_id)
    await ai_task_executor.run(task)
    await enhanced.refresh_from_db(); await task.refresh_from_db()
    assert enhanced.provider_task_id == 'accepted-enhancement', task.error_message
    assert submit.await_count == upload.await_count == 1
    await collect_export(enhanced); await collect_export(enhanced)
    await worker.step(operation); await operation.refresh_from_db()
    assert operation.result['stage'] == 'completed'
    assert operation.result['applied_to_scene'] is True
    scene = await Scene.get(id=video.scene_id)
    assert scene.metadata['current_video_id'] == operation.result['result_video_id']
    assert await ModelUsageRecord.filter(billing_type='media_processing').count() == 1
    assert await AiTask.filter(task_type=8).count() == 1
    assert submit.await_count == 1
    assert (await Video.get(id=video.id)).url == '/media/source.mp4'


@pytest.mark.asyncio
async def test_progress_failure_rolls_back_checkpoint_and_recovers_without_another_enhancement(tmp_path, monkeypatch):
    video, parent, _, _, _ = await setup_job(tmp_path, monkeypatch)
    worker = AutomaticEnhancementRecovery()
    operation = await AgentOperation.get(task=parent, key=KEY)
    original_save = Video.save
    async def fail_progress(instance, *args, **kwargs):
        if instance.id == video.id and (instance.metadata or {}).get('auto_enhancement', {}).get('stage') == 'enhancing':
            raise RuntimeError('Database write interrupted')
        return await original_save(instance, *args, **kwargs)
    monkeypatch.setattr(Video, 'save', fail_progress)
    with pytest.raises(RuntimeError):
        await worker.step(operation)
    await operation.refresh_from_db()
    assert operation.state == 'pending' and operation.result == {'stage': 'waiting_video'}
    assert await AiTask.filter(task_type=8).count() == 1
    monkeypatch.setattr(Video, 'save', original_save)
    await worker.step(operation); await operation.refresh_from_db()
    assert operation.result['stage'] == 'enhancing'
    assert await AiTask.filter(task_type=8).count() == 1


@pytest.mark.asyncio
async def test_parent_cancelled_during_quote_cannot_admit_paid_child(tmp_path, monkeypatch):
    from controllers.chapter_export import chapter_exports
    _, parent, _, _, _ = await setup_job(tmp_path, monkeypatch)
    original_quote = chapter_exports.quote
    async def cancel_during_quote(*args, **kwargs):
        result = await original_quote(*args, **kwargs)
        await AiTask.filter(id=parent.id).update(status=5)
        return result
    monkeypatch.setattr(chapter_exports, 'quote', cancel_during_quote)
    operation = await AgentOperation.get(task=parent, key=KEY)
    await AutomaticEnhancementRecovery().step(operation)
    assert await AiTask.filter(task_type=8).count() == 0


@pytest.mark.asyncio
async def test_price_change_during_quote_is_checked_again_at_child_admission(tmp_path, monkeypatch):
    from controllers.chapter_export import chapter_exports
    _, parent, config, _, _ = await setup_job(tmp_path, monkeypatch)
    original_quote = chapter_exports.quote
    async def change_price_before_quote(*args, **kwargs):
        config.pricing = {**config.pricing, 'discount': 0.25}
        await config.save()
        return await original_quote(*args, **kwargs)
    monkeypatch.setattr(chapter_exports, 'quote', change_price_before_quote)
    operation = await AgentOperation.get(task=parent, key=KEY)
    await AutomaticEnhancementRecovery().step(operation); await operation.refresh_from_db()
    assert operation.result['stage'] == 'needs_confirmation'
    assert await AiTask.filter(task_type=8).count() == 0
