"""Collect submitted exports independently of the browser and LLM execution timeout."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from models.agent_operation import AgentOperation
from tortoise.expressions import Q
from services.video_enhancement.contract import EnhancementOptions
from services.video_enhancement.media import export_media
from services.video_enhancement.provider import MediaKitClient, MediaKitError
from services.video_enhancement.settlement import settle_enhancement
from utils.messages import localized_message

logger = logging.getLogger(__name__)
_collectors: dict[int, asyncio.Task] = {}


async def collect_export(export: ChapterExport):
    task = await AiTask.get(id=export.task_id)
    from services.language import task_language
    token = task_language.set(task.request_params.get('prompt_language', 'en'))
    try:
        await _collect_export(task, export)
    finally:
        task_language.reset(token)


async def _collect_export(task: AiTask, export: ChapterExport):
    snapshot = task.request_params['config_snapshot']
    async with httpx.AsyncClient(timeout=120) as http:
        if export.provider_result.get('status') not in {'completed', 'failed'}:
            from controllers.config import ai_model_config_controller
            # Accepted operations must still be collected when new submissions are disabled.
            config = await ai_model_config_controller.get_configured_for_task(8, snapshot['id'], team_id=task.request_params.get('team_id'))
            provider = MediaKitClient.for_snapshot(snapshot, config, http=http)
            try:
                receipt = await provider.query(export.provider_task_id)
            except MediaKitError as error:
                if error.status_code not in {404, 410}:
                    raise
                from tortoise.transactions import in_transaction
                async with in_transaction():
                    current = await AiTask.filter(id=task.id).select_for_update().get()
                    export.provider_result = {**export.provider_result, 'query_unavailable': True}
                    export.collection_complete = True
                    await export.save(update_fields=['provider_result', 'collection_complete', 'updated_at'])
                    await AiTask.filter(id=task.id).update(status=5 if current.status == 5 else 4, stage='needs_review',
                        error_message=localized_message('供应商任务已无法查询，请人工核对用量和结果'))
                return
            await AiTask.filter(id=task.id).exclude(status=5).update(error_message=None)
            if receipt.status in {'running', 'processing'}:
                return
            export.provider_result = {'status': receipt.status, 'result': receipt.result,
                'expires_at': receipt.expires_at, 'error_code': (receipt.error or {}).get('code')}
            await export.save(update_fields=['provider_result', 'updated_at'])
        await ChapterExport.filter(id=export.id).update(submission_slot=False)
        billing_pending = False
        try:
            ledger = await settle_enhancement(task, export)
        except Exception:
            ledger = None
            billing_pending = True
        # Save the expiring result even if accounting is temporarily unavailable.
        if export.provider_result['status'] == 'failed':
            await AiTask.filter(id=task.id).exclude(status=5).update(status=4,
                stage='billing_pending' if billing_pending else 'failed', error_message=localized_message('供应商画质增强失败'))
            export.collection_complete = not billing_pending
            await export.save(update_fields=['collection_complete', 'updated_at'])
            return
        if not export.media_ref:
            expires = export.provider_result.get('expires_at')
            if expires and expires <= datetime.now(timezone.utc).timestamp():
                await AiTask.filter(id=task.id).exclude(status=5).update(status=4,
                    stage='billing_pending' if billing_pending else 'needs_review', error_message=localized_message('增强结果链接已过期，原片仍可使用'))
                export.collection_complete = not billing_pending
                await export.save(update_fields=['collection_complete', 'updated_at'])
                return
            await AiTask.filter(id=task.id).exclude(status=5).update(stage='saving_result')
            try:
                result = await export_media.save_enhanced(export, http)
            except ValueError as error:
                await AiTask.filter(id=task.id).exclude(status=5).update(status=4,
                    stage='billing_pending' if billing_pending else 'needs_review',error_message=str(error))
                export.collection_complete = not billing_pending
                await export.save(update_fields=['collection_complete','updated_at'])
                return
            export.media_ref, export.media_sha256, export.output_probe = result['ref'], result['sha256'], result['probe']
            await export.save(update_fields=['media_ref', 'media_sha256', 'output_probe', 'updated_at'])
        if billing_pending:
            await AiTask.filter(id=task.id).update(stage='billing_pending')
            return
        if ledger is None or ledger.usage.get('missing_usage'):
            await AiTask.filter(id=task.id).exclude(status=5).update(status=4, stage='needs_review', error_message=localized_message('增强结果已保存，实际用量待核对'))
        else:
            await AiTask.filter(id=task.id).exclude(status=5).update(status=3, stage='completed', progress=100,
                response_data={'export_id': export.id}, error_message=None, finished_at=datetime.now(timezone.utc))
        export.collection_complete = True
        await export.save(update_fields=['collection_complete', 'updated_at'])
        from services.creation_agent.production import finish_production_message
        await task.refresh_from_db()
        await finish_production_message(task)


async def collect_exports():
    for export_id, running in list(_collectors.items()):
        if running.done():
            running.result()
            del _collectors[export_id]
    for export in await ChapterExport.filter(collection_complete=False, provider_task_id__not_isnull=True).select_related('task').limit(20):
        if not export.task_id or export.id in _collectors:
            continue
        task = export.task
        options = EnhancementOptions.model_validate(task.request_params['config_snapshot']['processing_options'])
        now = datetime.now(timezone.utc)
        previous = export.provider_result.get('last_poll_at', 0)
        delay = min(300, options.poll_seconds * 2 ** min(export.provider_result.get('poll_failures', 0), 5))
        if now.timestamp() - previous < delay:
            continue
        _collectors[export.id] = asyncio.create_task(_leased_collection(export, now))


async def stop_collectors():
    for task in _collectors.values():
        task.cancel()
    await asyncio.gather(*_collectors.values(), return_exceptions=True)
    _collectors.clear()


async def _leased_collection(export, now):
    task = export.task
    owner = uuid4()
    claimed = await ChapterExport.filter(
        Q(collection_lease_until__isnull=True) | Q(collection_lease_until__lte=now),
        id=export.id, collection_complete=False,
    ).update(collection_owner=owner, collection_lease_until=now+timedelta(seconds=90))
    if not claimed:
        return

    async def heartbeat():
        while True:
            await asyncio.sleep(25)
            renewed = await ChapterExport.filter(id=export.id, collection_owner=owner).update(
                collection_lease_until=datetime.now(timezone.utc)+timedelta(seconds=90))
            if not renewed:
                raise RuntimeError('Export collection lease lost')

    # Only short atomic lease updates hold a DB lock; downloading never holds a transaction.
    work = asyncio.create_task(collect_export(export))
    renewal = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait({work, renewal}, return_when=asyncio.FIRST_COMPLETED)
        for completed in done:
            completed.result()
        await export.refresh_from_db()
        export.provider_result = {**export.provider_result, 'last_poll_at':now.timestamp(), 'poll_failures':0}
        await export.save(update_fields=['provider_result'])
    except Exception as error:
        logger.warning('Enhancement collection deferred: export_id=%s error_type=%s', export.id, type(error).__name__)
        message = localized_message('增强结果暂未保存，后台将重试查询或保存；请检查服务配置与网络',
            _language=task.request_params.get('prompt_language', 'en'))
        if isinstance(error, MediaKitError):
            message = str(error) + ': ' + message
        await AiTask.filter(id=task.id).exclude(status=5).update(error_message=message)
        await export.refresh_from_db()
        export.provider_result = {**export.provider_result, 'last_poll_at':now.timestamp(),
            'poll_failures':export.provider_result.get('poll_failures', 0)+1}
        await export.save(update_fields=['provider_result'])
    finally:
        work.cancel(); renewal.cancel()
        await asyncio.gather(work, renewal, return_exceptions=True)
        await ChapterExport.filter(id=export.id, collection_owner=owner).update(collection_owner=None, collection_lease_until=None)

async def recover_export(task) -> bool:
    if task.request_params.get('operation') != 'enhance_export':
        return False
    export = await ChapterExport.get_or_none(id=task.request_params['export_id'])
    if export is None:
        return False
    if not export.provider_task_id:
        receipt = await AgentOperation.get_or_none(task=task, key='media:enhance_export', state='completed')
        if receipt:
            export.provider_task_id = receipt.result.get('provider_task_id')
            await export.save(update_fields=['provider_task_id'])
    if export.provider_task_id:
        await AiTask.filter(id=task.id).update(status=2, stage='waiting_media')
        return True
    return False
