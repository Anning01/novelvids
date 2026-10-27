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
                export.source_media_ref = result['ref']
                export.source_sha256 = result['sha256']
                export.source_probe = result['probe']
                export.media_ref = result['ref']
                export.media_sha256 = result['sha256']
                export.output_probe = result['probe']
                await export.save(update_fields=['source_media_ref', 'source_sha256', 'source_probe',
                    'media_ref', 'media_sha256', 'output_probe', 'updated_at'])
            return {'export_id': export.id}

        return await execute_step(request_params['task_id'], 'prepare:chapter_export', prepare)


class EnhanceExportHandler(BaseTaskHandler):
    async def execute(self, request_params):
        import httpx
        from controllers.config import ai_model_config_controller
        from services.creation_agent.waiting import WaitingForMedia
        from services.video_enhancement.contract import EnhancementOptions
        from services.video_enhancement.provider import MediaKitClient, MediaKitError

        export = await ChapterExport.get(id=request_params['export_id'])
        snapshot = request_params['config_snapshot']
        options = EnhancementOptions.model_validate(snapshot['processing_options'])
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
            from services.creation_agent.skill_execution import current_execution
            execution = current_execution.get()
            if execution:
                await execution.before_request()
            current_config = await ai_model_config_controller.get_active(8, snapshot['id'], team_id=request_params.get('team_id'))
            async with httpx.AsyncClient(timeout=60) as http:
                client = MediaKitClient.for_snapshot(snapshot, current_config, http=http)
                started = True
                try:
                    task_id = await client.submit(url, export.identity_key, queue_id=options.queue_id)
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
            # Conservatively share one quota across all MediaKit configurations.
            anchor = await AiModelConfig.filter(task_type=8).order_by('id').using_db(db).first()
            await AiModelConfig.filter(id=anchor.id).using_db(db).update(updated_at=F('updated_at'))
            reserved = await ChapterExport.filter(submission_slot=True).exclude(id=export.id).using_db(db).count()
            quota = min(snapshot.get('concurrency', 1), options.account_concurrency)
            if reserved >= quota:
                await AiTask.filter(id=request_params['task_id']).using_db(db).update(status=6, stage='waiting_capacity')
            else:
                await ChapterExport.filter(id=export.id).using_db(db).update(submission_slot=True)
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
