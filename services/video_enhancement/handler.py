"""Deterministic preparation inside the existing assistant execution boundary."""

from models.chapter_export import ChapterExport
from services.ai_task_executor import BaseTaskHandler
from services.creation_agent.operation_receipts import execute_step
from services.video_enhancement.media import export_media
from utils.messages import localized_message


class PrepareExportHandler(BaseTaskHandler):
    def timeout_seconds(self, request_params):
        return 1200

    async def execute(self, request_params):
        export = await ChapterExport.get(id=request_params['export_id'])

        async def prepare():
            if not export.source_sha256:
                result = await export_media.compose(export)
                from tortoise.transactions import in_transaction
                async with in_transaction() as db:
                    changed = await ChapterExport.filter(id=export.id).using_db(db).update(
                        source_media_ref=result['ref'], source_sha256=result['sha256'], source_probe=result['probe'],
                        media_ref=result['ref'], media_sha256=result['sha256'], output_probe=result['probe'])
                    if not changed:
                        from services.deleted_media import enqueue_media
                        await enqueue_media([result['ref']], export.team_id)
                if not changed:
                    raise ValueError(localized_message('导出记录不存在'))
            return {'export_id': export.id}

        return await execute_step(request_params['task_id'], 'prepare:chapter_export', prepare)


class EnhanceExportHandler(BaseTaskHandler):
    async def execute(self, request_params):
        import httpx
        from controllers.config import ai_model_config_controller
        from services.creation_agent.waiting import WaitingForMedia
        from services.video_enhancement.contract import EnhancementOptions, MediaProbe, require_upscale, validate_source, RESOLUTION_SHORT_SIDE
        from services.video_enhancement.provider import MediaKitClient, MediaKitError

        export = await ChapterExport.get(id=request_params['export_id'])
        snapshot = request_params['config_snapshot']
        options = EnhancementOptions.model_validate(snapshot['processing_options'])
        probe = MediaProbe.model_validate(export.source_probe)
        resolution = (export.recipe or {}).get('resolution', '1080p')
        if resolution not in options.output_resolutions:
            raise ValueError(localized_message('增强服务未启用所选清晰度'))
        require_upscale(probe, RESOLUTION_SHORT_SIDE[resolution])
        validate_source(probe, options)
        config = await ai_model_config_controller.get_active(8, snapshot['id'], team_id=request_params.get('team_id'))
        if export.source_media_ref.startswith('/media/'):
            async def upload():
                import asyncio
                from services.video_enhancement.media import file_digest
                async with export_media.materialize(export.source_media_ref) as path:
                    if await asyncio.to_thread(file_digest, path) != export.source_sha256:
                        raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
                    async with httpx.AsyncClient(timeout=300) as http:
                        uploaded = await MediaKitClient.for_snapshot(snapshot, config, http=http).upload(path, max_bytes=options.local_upload_max_bytes)
                        return {'file_id': uploaded}
            uploaded = await execute_step(request_params['task_id'], 'upload:enhancement_source', upload)
            url = uploaded['file_id']
        else:
            url = export_media.input_url(export.source_media_ref, options.media_base_url)
        started = False

        async def submit():
            nonlocal started
            origin = request_params.get('origin_run_id')
            if origin and await AiTask.filter(id=origin, status__in=[4, 5]).exists():
                raise ValueError(localized_message('运行已停止，不能提交后续步骤'))
            from services.creation_agent.skill_execution import current_execution
            execution = current_execution.get()
            if execution:
                await execution.before_request()
            current_config = await ai_model_config_controller.get_active(8, snapshot['id'], team_id=request_params.get('team_id'))
            async with httpx.AsyncClient(timeout=60) as http:
                client = MediaKitClient.for_snapshot(snapshot, current_config, http=http, task_id=request_params['task_id'])
                started = True
                try:
                    task_id = await client.submit(url, request_params.get('provider_client_token') or export.identity_key,
                        queue_id=options.queue_id, resolution=resolution)
                except MediaKitError as error:
                    if error.definite_rejection:
                        started = False
                    raise
                # Persist the accepted ID before returning the external receipt.
                await ChapterExport.filter(id=export.id).update(provider_task_id=task_id)
                return {'provider_task_id': task_id,'provider_request_id':client.last_request_id}

        from models.config import AiModelConfig
        from models.ai_task import AiTask
        from tortoise.transactions import in_transaction
        from tortoise.expressions import F
        capacity_available = False
        async with in_transaction() as db:
            await AiModelConfig.filter(id=config.id).using_db(db).update(concurrency=F('concurrency'))
            current = await AiModelConfig.filter(id=config.id).using_db(db).select_for_update().get()
            occupied = await ChapterExport.filter(submission_slot=True).exclude(id=export.id).using_db(db).select_related('task')
            # Keep legacy reservations with no task until their existing recovery releases them.
            reserved = sum(row.task is None or row.task.request_params.get('model_config_id') == config.id for row in occupied)
            quota = current.concurrency
            if reserved >= quota:
                await AiTask.filter(id=request_params['task_id']).using_db(db).update(status=6, stage='waiting_capacity')
            else:
                if not await ChapterExport.filter(id=export.id).using_db(db).update(submission_slot=True):
                    raise ValueError(localized_message('章节不存在'))
                capacity_available = True
        if not capacity_available:
            raise WaitingForMedia({'export_id':export.id})
        try:
            receipt = await execute_step(request_params['task_id'], 'media:enhance_export', submit,
                external=True, external_started=lambda: started)
        except BaseException:
            if not started:
                await ChapterExport.filter(id=export.id).update(submission_slot=False)
            raise
        await ChapterExport.filter(id=export.id).update(provider_task_id=receipt['provider_task_id'])
        raise WaitingForMedia({'export_id':export.id})
