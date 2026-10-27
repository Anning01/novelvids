"""Scoped export admission and quote orchestration over reusable media services."""

from fastapi import HTTPException

from auth.deps import AuthContext, ensure_novel_access, require_roles
from controllers.config import ai_model_config_controller
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from services.creation_agent.skill_execution import prepare_workflow, require_agent
from services.creation_agent.submissions import bind_submission, previous_submission
from services.creation_objects import project_write
from services.video_enhancement.contract import EnhancementOptions, MediaProbe, enhancement_cost, validate_source
from services.video_enhancement.media import digest, export_media
from services.video_enhancement.sources import current_selection, freeze_chapter, require_generation_scope
from utils.messages import localized_message
from utils.enums import AiTaskTypeEnum


class ChapterExports:
    async def _enhancement(self, source, recipe, ctx):
        legacy = digest(['enhance', source.novel_id, ctx.team_id, source.source_sha256, recipe])
        existing = await ChapterExport.get_or_none(identity_key=legacy)
        if existing and existing.chapter_id == source.chapter_id:
            return existing, legacy
        identity = digest([legacy, source.chapter_id])
        return await ChapterExport.get_or_none(identity_key=identity), identity

    async def get(self, export_id: int, ctx: AuthContext) -> ChapterExport:
        export = await ChapterExport.get_or_none(id=export_id)
        if export is None:
            raise HTTPException(404, localized_message('导出记录不存在'))
        await ensure_novel_access(export.novel_id, ctx)
        return export

    async def prepare(self, chapter_id: int, ctx: AuthContext, *, expected_version: str | None = None):
        await require_roles('admin', 'creator')(ctx)
        chapter = await Chapter.get_or_none(id=chapter_id)
        if chapter is None:
            raise HTTPException(404, localized_message('章节不存在'))
        await ensure_novel_access(chapter.novel_id, ctx)
        await require_generation_scope(chapter.novel_id, ctx.team_id)
        await require_agent(ctx.team_id)
        manifest, version = await freeze_chapter(chapter_id)
        if expected_version is not None and expected_version != version:
            raise HTTPException(409, localized_message('原片来源已变化，请重新准备成片'))
        identity = digest(['source', chapter.novel_id, ctx.team_id, version])
        params = await prepare_workflow({'operation': 'prepare_export', 'novel_id': chapter.novel_id,
            'chapter_id': chapter_id, 'team_id': ctx.team_id, 'user_id': ctx.user.id if ctx.user else None})
        from services.ai_task_executor import ai_task_executor
        from models.ai_task import AiTask
        async with project_write(chapter.novel_id) as db:
            selected = [{key:item[key] for key in ('scene_id', 'sequence', 'video_id')} for item in manifest]
            if await current_selection(chapter_id) != selected:
                raise HTTPException(409, localized_message('原片来源已变化，请重新准备成片'))
            previous = await previous_submission(4, params, db)
            if previous:
                return await ChapterExport.get(task=previous), previous
            export = await ChapterExport.get_or_none(identity_key=identity).using_db(db)
            if export and export.task_id:
                task = await AiTask.get(id=export.task_id).using_db(db)
                return export, await bind_submission(task, params)
            export = await ChapterExport.create(novel_id=chapter.novel_id, chapter_id=chapter_id,
                team_id=ctx.team_id, created_by=ctx.user.id if ctx.user else None,
                identity_key=identity, source_version=version, manifest=manifest, using_db=db)
            params['export_id'] = export.id
            task = await ai_task_executor.submit(AiTaskTypeEnum.video, params, db_connection=db)
            export.task_id = task.id
            await export.save(using_db=db, update_fields=['task_id'])
            return export, task

    async def quote(self, export: ChapterExport, config_id: int, ctx: AuthContext) -> dict:
        await ensure_novel_access(export.novel_id, ctx)
        await require_generation_scope(export.novel_id, ctx.team_id)
        if export.parent_export_id is not None:
            export = await self.get(export.parent_export_id, ctx)
        if not export.source_media_ref or not export.source_sha256:
            raise HTTPException(409, localized_message('请先完成原片准备'))
        config = await ai_model_config_controller.get_active(8, config_id, team_id=ctx.team_id)
        allowed = await self.configs(ctx)
        if config.id not in {row.id for row in allowed}:
            raise HTTPException(403, localized_message('所选模型不可用'))
        options = EnhancementOptions.model_validate(config.processing_options or {})
        probe = MediaProbe.model_validate(export.source_probe)
        validate_source(probe, options)
        if not export.source_media_ref.startswith('/media/'):
            export_media.input_url(export.source_media_ref, options.media_base_url)
        snapshot = {name: getattr(config, name) for name in ('id', 'name', 'model', 'base_url', 'api_protocol',
            'scope', 'team_id', 'processing_options', 'pricing', 'concurrency')}
        snapshot['processing_options'] = options.model_dump(mode='json')
        price = enhancement_cost(probe.duration, 1080, probe.fps, config.pricing)
        recipe = {'version': 1, 'config_id': config.id, 'resolution': '1080p', 'fps_mode': 'source'}
        reusable, _ = await self._enhancement(export, recipe, ctx)
        if reusable and (not reusable.media_ref or not await ChapterExport.filter(id=reusable.id, task__status=3).exists()):
            reusable = None
        if reusable:
            price = 0
        return {'amount': str(price), 'currency': 'CNY', 'source_sha256': export.source_sha256,
            'quote_version': digest([export.id, export.source_sha256, recipe, snapshot]),
            'recipe': recipe, 'config_snapshot': snapshot, 'reused_export_id': reusable.id if reusable else None}

    async def enhance(self, export_id: int, request, ctx: AuthContext):
        await require_roles('admin', 'creator')(ctx)
        source = await self.get(export_id, ctx)
        if source.parent_export_id is not None:
            source = await self.get(source.parent_export_id, ctx)
        quote = await self.quote(source, request.model_config_id, ctx)
        if request.source_sha256 != source.source_sha256 or request.quote_version != quote['quote_version']:
            raise HTTPException(409, localized_message('来源或报价已变化，请重新确认'))
        # Content is rechecked before admitting a paid operation; never trust only the displayed hash.
        from services.video_enhancement.media import file_digest
        import asyncio
        async with export_media.materialize(source.source_media_ref) as path:
            if await asyncio.to_thread(file_digest, path) != source.source_sha256:
                raise HTTPException(409, localized_message('原片来源已变化，请重新准备成片'))
        params = await prepare_workflow({'operation': 'enhance_export', 'novel_id': source.novel_id,
            'chapter_id': source.chapter_id, 'team_id': ctx.team_id, 'user_id': ctx.user.id if ctx.user else None,
            'model_config_id': request.model_config_id, 'config_snapshot': quote['config_snapshot']})
        from models.ai_task import AiTask
        from services.ai_task_executor import ai_task_executor
        async with project_write(source.novel_id) as db:
            previous = await previous_submission(8, params, db)
            if previous:
                return await ChapterExport.get(task=previous), previous
            existing, identity = await self._enhancement(source, quote['recipe'], ctx)
            if existing and existing.task_id:
                task = await AiTask.get(id=existing.task_id).using_db(db)
                return existing, await bind_submission(task, params)
            export = await ChapterExport.create(novel_id=source.novel_id, chapter_id=source.chapter_id,
                team_id=ctx.team_id, created_by=ctx.user.id if ctx.user else None, parent_export_id=source.id,
                identity_key=identity, source_version=source.source_version, manifest=source.manifest,
                source_media_ref=source.source_media_ref, source_sha256=source.source_sha256,
                source_probe=source.source_probe, recipe=quote['recipe'], using_db=db)
            task = await ai_task_executor.submit(AiTaskTypeEnum.video_enhancement, {**params, 'export_id': export.id}, db_connection=db)
            export.task_id = task.id
            await export.save(using_db=db, update_fields=['task_id'])
            return export, task

    async def configs(self, ctx):
        from services.model_resolution import resolve_scope_configs
        return await resolve_scope_configs(8, ctx.team_id,
            capability_filter=lambda row: row.api_protocol == 'volcengine_mediakit' and row.model == 'enhance-video-generative')

    async def describe(self, export: ChapterExport, selection: list[dict] | None = None) -> dict:
        from models.ai_task import AiTask
        task = await AiTask.get_or_none(id=export.task_id)
        if selection is None:
            from services.video_enhancement.sources import current_selection
            selection = await current_selection(export.chapter_id)
        recorded = [{key:item.get(key) for key in ('scene_id','sequence','video_id')} for item in export.manifest]
        return {'id': export.id, 'chapter_id': export.chapter_id, 'parent_export_id': export.parent_export_id,
            'selection_current': selection == recorded,
            'source_version': export.source_version, 'source_sha256': export.source_sha256,
            'source_probe': export.source_probe, 'output_probe': export.output_probe,
            'source_url': f'/api/video/exports/{export.id}/download?source=true' if export.source_media_ref else None,
            'url': f'/api/video/exports/{export.id}/download' if export.media_ref else None,
            'task_id': str(export.task_id) if export.task_id else None,
            'status': task.status if task else None, 'stage': task.stage if task else None,
            'error': task.error_message if task else None, 'created_at': export.created_at.isoformat(),
            'recipe': export.recipe}


chapter_exports = ChapterExports()
