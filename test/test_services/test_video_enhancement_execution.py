from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta

import pytest

from models.ai_task import AiTask
from models.config import AiModelConfig
from models.chapter_export import ChapterExport
from models.agent_operation import AgentOperation
from services.creation_agent.waiting import WaitingForMedia
from services.video_enhancement.contract import EnhancementOptions
from services.video_enhancement.handler import EnhanceExportHandler
from services.video_enhancement.provider import MediaKitError, MediaKitTask
from services.video_enhancement.recovery import collect_export, collect_exports, stop_collectors
from test.test_services.test_video_enhancement_billing import completed_export


async def pending_export():
    task, export=await completed_export()
    cfg=await AiModelConfig.get(id=task.request_params['config_snapshot']['id'])
    cfg.is_active=True;await cfg.save()
    task.request_params.update(task_id=str(task.id),export_id=export.id,model_config_id=cfg.id)
    task.request_params['config_snapshot'].update(base_url=cfg.base_url,concurrency=1,
        processing_options=EnhancementOptions(media_base_url='https://media.example').model_dump(mode='json'))
    await task.save()
    export.provider_task_id=None;export.provider_result={};export.source_media_ref='https://media.example/source.mp4'
    export.source_probe={'duration':'5','width':864,'height':496,'fps':'24'}
    await export.save()
    return task,export,cfg


@pytest.mark.asyncio
async def test_submission_checkpoint_and_replay_only_return_the_same_provider_task():
    task,export,_=await pending_export()
    with patch('services.video_enhancement.provider.MediaKitClient.submit',AsyncMock(return_value='accepted')) as submit:
        for _ in range(2):
            with pytest.raises(WaitingForMedia):await EnhanceExportHandler().execute(task.request_params)
    submit.assert_awaited_once()
    await export.refresh_from_db()
    assert export.provider_task_id=='accepted'
    assert (await AgentOperation.get(task=task,key='media:enhance_export')).state=='completed'


@pytest.mark.asyncio
@pytest.mark.parametrize('definite',[False,True])
async def test_unknown_submission_keeps_its_slot_while_definite_rejection_releases_it(definite):
    task,export,_=await pending_export()
    with patch('services.video_enhancement.provider.MediaKitClient.submit',AsyncMock(side_effect=MediaKitError('failure',definite_rejection=definite))):
        with pytest.raises(MediaKitError):await EnhanceExportHandler().execute(task.request_params)
    await export.refresh_from_db()
    assert export.submission_slot is not definite
    assert (await AgentOperation.get(task=task,key='media:enhance_export')).state==('failed' if definite else 'uncertain')


@pytest.mark.asyncio
async def test_capacity_wait_is_committed_and_does_not_submit():
    task,export,_=await pending_export()
    await ChapterExport.create(novel_id=1,chapter_id=1,identity_key='c'*64,source_version='d'*64,submission_slot=True)
    with patch('services.video_enhancement.provider.MediaKitClient.submit',AsyncMock()) as submit:
        with pytest.raises(WaitingForMedia):await EnhanceExportHandler().execute(task.request_params)
        submit.assert_not_awaited()
    await task.refresh_from_db()
    assert task.status==6 and task.stage=='waiting_capacity'


@pytest.mark.asyncio
async def test_running_query_does_not_save_or_settle_then_failed_query_releases_slot():
    task,export,cfg=await pending_export()
    export.provider_task_id='accepted';export.submission_slot=True;await export.save()
    with patch('services.video_enhancement.provider.MediaKitClient.query',AsyncMock(return_value=MediaKitTask(task_id='accepted',status='running'))):
        await collect_export(export)
    assert not export.collection_complete
    with patch('services.video_enhancement.provider.MediaKitClient.query',AsyncMock(return_value=MediaKitTask(task_id='accepted',status='failed',error={'code':'Unsupported'}))):
        await collect_export(export)
    await export.refresh_from_db();await task.refresh_from_db()
    assert not export.submission_slot and export.collection_complete and task.status==4


@pytest.mark.asyncio
async def test_expired_completed_result_is_billed_without_resubmitting():
    task,export,cfg=await pending_export()
    export.provider_task_id='accepted'
    export.provider_result={'status':'completed','result':{'duration':5,'fps':24,'resolution':'1080p'},'expires_at':1}
    await export.save()
    with patch('services.video_enhancement.provider.MediaKitClient.submit',AsyncMock()) as submit:
        await collect_export(export)
        submit.assert_not_awaited()
    await task.refresh_from_db()
    assert task.stage=='needs_review' and task.status==4


@pytest.mark.asyncio
async def test_collector_lease_prevents_a_second_worker_and_shutdown_is_clean():
    task,export,_=await pending_export()
    export.provider_task_id='accepted';export.collection_owner='11111111-1111-1111-1111-111111111111'
    export.collection_lease_until=datetime.now(timezone.utc)+timedelta(seconds=120);await export.save()
    with patch('services.video_enhancement.recovery.collect_export',AsyncMock()) as collect:
        await collect_exports()
        import asyncio
        await asyncio.sleep(.02)
        await collect_exports()
        await asyncio.sleep(.02)
        collect.assert_not_awaited()
    await stop_collectors()


@pytest.mark.asyncio
async def test_poll_failures_back_off_without_holding_the_collection_lease():
    from services.video_enhancement.recovery import _leased_collection, _collectors
    task, export, _ = await pending_export()
    export.provider_task_id = 'accepted'
    await export.save()
    now = datetime.now(timezone.utc)
    with patch('services.video_enhancement.recovery.collect_export', AsyncMock(side_effect=TimeoutError)) as collect:
        export.task = task
        await _leased_collection(export, now)
        await export.refresh_from_db()
        assert export.provider_result['poll_failures'] == 1
        assert export.collection_owner is None and export.collection_lease_until is None
        await collect_exports()
        assert not _collectors
        collect.assert_awaited_once()
    await stop_collectors()


@pytest.mark.asyncio
async def test_cancelled_before_submission_never_calls_media_provider():
    task, export, _ = await pending_export()
    task.status = 5
    await task.save()
    with patch('services.video_enhancement.provider.MediaKitClient.submit', AsyncMock()) as submit:
        with pytest.raises(ValueError):
            await EnhanceExportHandler().execute(task.request_params)
        submit.assert_not_awaited()
    await export.refresh_from_db()
    assert not export.submission_slot


@pytest.mark.asyncio
async def test_local_export_upload_and_paid_submission_are_both_reused_on_replay(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from services.video_enhancement.media import export_media, file_digest
    task, export, _ = await pending_export()
    path = tmp_path/'frozen.mp4'
    path.write_bytes(b'immutable source')
    export.source_media_ref = '/media/exports/1/source.mp4'
    export.source_sha256 = file_digest(path)
    await export.save()
    @asynccontextmanager
    async def materialize(_ref):
        yield path
    monkeypatch.setattr(export_media, 'materialize', materialize)
    with patch('services.video_enhancement.provider.MediaKitClient.upload', AsyncMock(return_value='mediakit://frozen')) as upload, \
         patch('services.video_enhancement.provider.MediaKitClient.submit', AsyncMock(return_value='accepted')) as submit:
        for _ in range(2):
            with pytest.raises(WaitingForMedia):
                await EnhanceExportHandler().execute(task.request_params)
        upload.assert_awaited_once()
        submit.assert_awaited_once_with('mediakit://frozen', export.identity_key, queue_id=None, resolution='1080p')


@pytest.mark.asyncio
@pytest.mark.parametrize('status_code', [404, 410])
@pytest.mark.parametrize('cancelled', [False, True])
async def test_unqueryable_accepted_task_requires_review_and_never_resubmits(status_code, cancelled):
    from test.test_services.test_skill_workflow import enabled_project
    from schemas.ai_task import TaskReviewResolution
    from services.creation_agent.review import close_uncertain_task
    from fastapi import HTTPException
    novel, chapter, _ = await enabled_project()
    task, export, _ = await pending_export()
    task.request_params['novel_id'] = novel.id
    task.status = 5 if cancelled else 2
    export.novel_id, export.chapter_id = novel.id, chapter.id
    export.provider_task_id = 'accepted-but-expired'
    export.submission_slot = True
    await task.save(); await export.save()
    with patch('services.video_enhancement.provider.MediaKitClient.query', AsyncMock(side_effect=MediaKitError('Task not found',status_code=status_code))), \
         patch('services.video_enhancement.provider.MediaKitClient.submit', AsyncMock()) as submit:
        await collect_export(export)
        submit.assert_not_awaited()
    await task.refresh_from_db(); await export.refresh_from_db()
    assert task.status == (5 if cancelled else 4) and task.stage == 'needs_review'
    assert export.collection_complete and export.provider_result['query_unavailable']
    assert export.submission_slot  # Unknown outcome keeps its reservation until an audited closure.
    with pytest.raises(HTTPException):
        await close_uncertain_task(task.id, TaskReviewResolution(outcome='not_submitted',note='An accepted ID cannot mean never submitted.'))
    await close_uncertain_task(task.id, TaskReviewResolution(outcome='completed_unrecoverable',note='Operator checked the provider history; result is unavailable.'))
    await export.refresh_from_db(); await task.refresh_from_db()
    assert not export.submission_slot and task.stage == 'review_closed'
    assert task.status == (5 if cancelled else 4)
    assert task.request_params['review_certainty']['missing_usage'] is True


@pytest.mark.asyncio
async def test_permissions_are_rechecked_after_upload_before_paid_submission():
    from services.creation_agent.skill_execution import current_execution
    from types import SimpleNamespace
    task, export, _ = await pending_export()
    recheck = AsyncMock(side_effect=ValueError('Access revoked'))
    token = current_execution.set(SimpleNamespace(before_request=recheck))
    try:
        with patch('services.video_enhancement.provider.MediaKitClient.submit', AsyncMock()) as submit:
            with pytest.raises(ValueError,match='Access revoked'):
                await EnhanceExportHandler().execute(task.request_params)
            submit.assert_not_awaited()
    finally:
        current_execution.reset(token)
    await export.refresh_from_db()
    assert not export.submission_slot
    assert (await AgentOperation.get(task=task,key='media:enhance_export')).state == 'failed'
