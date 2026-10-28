from unittest.mock import AsyncMock,patch

import pytest

from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from models.agent_operation import AgentOperation
from services.video_enhancement.media import export_media
from services.video_enhancement.provider import MediaKitTask
from services.video_enhancement.recovery import collect_export,recover_export
from test.test_services.test_video_enhancement_billing import completed_export


@pytest.mark.asyncio
async def test_restart_recovers_accepted_id_without_replaying_submission():
    task,export=await completed_export()
    export.provider_task_id=None
    await export.save()
    task.request_params={**task.request_params,'operation':'enhance_export','export_id':export.id}
    await task.save()
    await AgentOperation.create(task=task,key='media:enhance_export',state='completed',result={'provider_task_id':'accepted'})
    assert await recover_export(task) is True
    await task.refresh_from_db();await export.refresh_from_db()
    assert task.stage=='waiting_media' and export.provider_task_id=='accepted'


@pytest.mark.asyncio
async def test_download_failure_retries_only_saving_and_bills_the_provider_success_once():
    task,export=await completed_export()
    task.request_params['config_snapshot']['base_url']='https://mediakit.example'
    await task.save()
    from models.config import AiModelConfig
    config=await AiModelConfig.get(id=task.request_params['config_snapshot']['id'])
    with patch('controllers.config.ai_model_config_controller.get_configured_for_task',AsyncMock(return_value=config)), \
         patch.object(export_media,'save_enhanced',AsyncMock(side_effect=TimeoutError)):
        with pytest.raises(TimeoutError):await collect_export(export)
    from models.usage_record import ModelUsageRecord
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count()==1
    saved={'ref':'/media/exports/ready.mp4','sha256':'a'*64,'probe':{'duration':'5','width':1920,'height':1080,'fps':'24'}}
    with patch('controllers.config.ai_model_config_controller.get_configured_for_task',AsyncMock(return_value=config)), \
         patch.object(export_media,'save_enhanced',AsyncMock(return_value=saved)), \
         patch('services.video_enhancement.provider.MediaKitClient.query',AsyncMock()) as query:
        await collect_export(export)
        query.assert_not_awaited()
    await task.refresh_from_db();await export.refresh_from_db()
    assert task.status==3 and export.collection_complete
    assert export.media_ref==saved['ref']
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count()==1


@pytest.mark.asyncio
async def test_cancelled_provider_operation_is_collected_but_does_not_become_success():
    task,export=await completed_export()
    task.status=5
    task.request_params['config_snapshot']['base_url']='https://mediakit.example'
    await task.save()
    saved={'ref':'/media/exports/ready.mp4','sha256':'a'*64,'probe':{'duration':'5','width':1920,'height':1080,'fps':'24'}}
    from models.config import AiModelConfig
    config=await AiModelConfig.get(id=task.request_params['config_snapshot']['id'])
    with patch('controllers.config.ai_model_config_controller.get_configured_for_task',AsyncMock(return_value=config)), \
         patch.object(export_media,'save_enhanced',AsyncMock(return_value=saved)):
        await collect_export(export)
    await task.refresh_from_db();await export.refresh_from_db()
    assert task.status==5
    assert export.collection_complete and export.media_ref


@pytest.mark.asyncio
async def test_billing_outage_does_not_delay_saving_expiring_media_and_recovery_only_retries_billing():
    task, export = await completed_export()
    export.submission_slot = True
    await export.save()
    saved = {'ref':'/media/exports/ready.mp4','sha256':'a'*64,'probe':{'duration':'5','width':1920,'height':1080,'fps':'24'}}
    with patch('services.video_enhancement.recovery.settle_enhancement', AsyncMock(side_effect=RuntimeError)), \
         patch.object(export_media, 'save_enhanced', AsyncMock(return_value=saved)) as save:
        await collect_export(export)
        save.assert_awaited_once()
    await task.refresh_from_db(); await export.refresh_from_db()
    assert task.stage == 'billing_pending'
    assert export.media_ref == saved['ref']
    assert not export.collection_complete and not export.submission_slot
    with patch.object(export_media, 'save_enhanced', AsyncMock()) as save, \
         patch('services.video_enhancement.provider.MediaKitClient.query', AsyncMock()) as query:
        await collect_export(export)
        save.assert_not_awaited(); query.assert_not_awaited()
    await task.refresh_from_db(); await export.refresh_from_db()
    from models.usage_record import ModelUsageRecord
    assert task.status == 3 and export.collection_complete
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('missing, expired', [(True, False), (False, True)])
async def test_cancelled_collection_keeps_cancelled_status_when_usage_or_file_needs_review(missing, expired):
    task, export = await completed_export(missing=missing)
    task.status = 5
    task.request_params['prompt_language'] = 'en'
    await task.save()
    if expired:
        export.provider_result['expires_at'] = 1
        await export.save()
    saved = {'ref':'/media/exports/ready.mp4','sha256':'a'*64,'probe':{}}
    with patch.object(export_media, 'save_enhanced', AsyncMock(return_value=saved)):
        await collect_export(export)
    await task.refresh_from_db(); await export.refresh_from_db()
    assert task.status == 5 and export.collection_complete


@pytest.mark.asyncio
async def test_collection_error_uses_frozen_task_language():
    from utils.prompt_language import task_language
    task, export = await completed_export()
    task.request_params['prompt_language'] = 'en'
    export.provider_result['expires_at'] = 1
    await task.save(); await export.save()
    token = task_language.set('zh')
    try:
        await collect_export(export)
        assert task_language.get() == 'zh'
    finally:
        task_language.reset(token)
    await task.refresh_from_db()
    assert 'expired' in task.error_message.lower()
