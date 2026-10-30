"""Scoped export admission and quote orchestration over reusable media services."""

from fastapi import HTTPException

from auth.deps import AuthContext, ensure_novel_access, require_roles
from controllers.config import ai_model_config_controller
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from services.creation_agent.skill_execution import prepare_workflow, require_agent
from services.creation_agent.submissions import bind_submission, previous_submission
from services.creation_objects import project_write
from services.video_enhancement.contract import EnhancementOptions, MediaProbe, enhancement_cost, validate_source, require_upscale, RESOLUTION_SHORT_SIDE
from services.video_enhancement.media import digest, export_media
from services.video_enhancement.sources import current_selection, freeze_chapter, freeze_video, require_generation_scope
from utils.messages import localized_message
from utils.enums import AiTaskTypeEnum


class ChapterExports:
    async def _enhancement(self, source, recipe, ctx, *, sha=None):
        sha = sha or source.source_sha256
        if source.source_video_id is not None:
            identity = digest(['video-enhance', source.novel_id, ctx.team_id, source.source_video_id, sha, recipe])
            return await ChapterExport.get_or_none(identity_key=identity), identity
        legacy = digest(['enhance', source.novel_id, ctx.team_id, sha, recipe])
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
        return await self._prepare(chapter, manifest, version, ctx)

    async def prepare_video(self, video_id: int, ctx: AuthContext):
        from models.video import Video
        from models.scene import Scene
        await require_roles('admin', 'creator')(ctx)
        video = await Video.get_or_none(id=video_id)
        if video is None:
            raise HTTPException(404, localized_message('视频不存在'))
        scene = await Scene.get(id=video.scene_id)
        chapter = await Chapter.get(id=scene.chapter_id)
        await ensure_novel_access(chapter.novel_id, ctx)
        await require_generation_scope(chapter.novel_id, ctx.team_id)
        await require_agent(ctx.team_id)
        manifest, version = await freeze_video(video, scene)
        return await self._prepare(chapter, manifest, version, ctx, video_id=video.id)

    async def _prepare(self, chapter, manifest, version, ctx, *, video_id=None):
        chapter_id = chapter.id
        identity = digest(['source', chapter.novel_id, ctx.team_id, version])
        params = await prepare_workflow({'operation': 'prepare_export', 'novel_id': chapter.novel_id,
            'chapter_id': chapter_id, 'source_video_id':video_id, 'team_id': ctx.team_id, 'user_id': ctx.user.id if ctx.user else None})
        from services.ai_task_executor import ai_task_executor
        from models.ai_task import AiTask
        async with project_write(chapter.novel_id) as db:
            selected = [{key:item[key] for key in ('scene_id', 'sequence', 'video_id')} for item in manifest]
            if video_id is not None:
                from models.video import Video
                if not await Video.filter(id=video_id,scene_id=manifest[0]['scene_id'],status=3).exists():
                    raise HTTPException(409, localized_message('原片来源已变化，请重新准备成片'))
            elif await current_selection(chapter_id) != selected:
                raise HTTPException(409, localized_message('原片来源已变化，请重新准备成片'))
            previous = await previous_submission(4, params, db)
            if previous:
                return await ChapterExport.get(task=previous), previous
            export = await ChapterExport.get_or_none(identity_key=identity).using_db(db)
            if export and export.task_id:
                task = await AiTask.get(id=export.task_id).using_db(db)
                return export, await bind_submission(task, params)
            export = await ChapterExport.create(novel_id=chapter.novel_id, chapter_id=chapter_id,
                source_video_id=video_id,
                team_id=ctx.team_id, created_by=ctx.user.id if ctx.user else None,
                identity_key=identity, source_version=version, manifest=manifest, using_db=db)
            params['export_id'] = export.id
            task = await ai_task_executor.submit(AiTaskTypeEnum.video, params, db_connection=db)
            export.task_id = task.id
            await export.save(using_db=db, update_fields=['task_id'])
            return export, task

    async def quote(self, export: ChapterExport, config_id: int, ctx: AuthContext, resolution: str = '1080p') -> dict:
        await ensure_novel_access(export.novel_id, ctx)
        await require_generation_scope(export.novel_id, ctx.team_id)
        ref, sha, source_probe = await self.enhancement_source(export)
        if not ref or not sha:
            raise HTTPException(409, localized_message('请先完成原片准备'))
        config = await ai_model_config_controller.get_active(8, config_id, team_id=ctx.team_id)
        allowed = await self.configs(ctx)
        if config.id not in {row.id for row in allowed}:
            raise HTTPException(403, localized_message('所选模型不可用'))
        options = EnhancementOptions.model_validate(config.processing_options or {})
        if resolution not in options.output_resolutions or resolution not in RESOLUTION_SHORT_SIDE:
            raise ValueError(localized_message('增强服务未启用所选清晰度'))
        probe = MediaProbe.model_validate(source_probe)
        require_upscale(probe, RESOLUTION_SHORT_SIDE[resolution])
        validate_source(probe, options)
        if not ref.startswith('/media/'):
            export_media.input_url(ref, options.media_base_url)
        snapshot = {name: getattr(config, name) for name in ('id', 'name', 'model', 'base_url', 'api_protocol',
            'scope', 'team_id', 'processing_options', 'pricing', 'concurrency')}
        snapshot['processing_options'] = options.model_dump(mode='json')
        price = enhancement_cost(probe.duration, RESOLUTION_SHORT_SIDE[resolution], probe.fps, config.pricing)
        recipe = {'version': 1, 'config_id': config.id, 'resolution': resolution, 'fps_mode': 'source'}
        # Enhanced inputs use their own bytes, never silently fall back to the original.
        reusable, _ = await self._enhancement(export, recipe, ctx, sha=sha)
        if reusable and (not reusable.media_ref or not await ChapterExport.filter(id=reusable.id, task__status=3).exists()):
            reusable = None
        if reusable:
            price = 0
        return {'amount': str(price), 'currency': 'CNY', 'source_sha256': sha,
            'quote_version': digest([export.id, sha, recipe, snapshot]),
            'recipe': recipe, 'config_snapshot': snapshot, 'reused_export_id': reusable.id if reusable else None}

    async def enhancement_source(self, export):
        if export.parent_export_id is not None:
            if not export.media_ref or not await ChapterExport.filter(id=export.id, task__status=3).exists():
                raise ValueError(localized_message('请先选择已生成成功的视频'))
            return export.media_ref, export.media_sha256, export.output_probe
        return export.source_media_ref, export.source_sha256, export.source_probe

    async def enhance(self, export_id: int, request, ctx: AuthContext):
        await require_roles('admin', 'creator')(ctx)
        source = await self.get(export_id, ctx)
        quote = await self.quote(source, request.model_config_id, ctx, request.resolution)
        ref, sha, probe = await self.enhancement_source(source)
        if request.source_sha256 != sha or request.quote_version != quote['quote_version']:
            raise HTTPException(409, localized_message('来源或报价已变化，请重新确认'))
        # Content is rechecked before admitting a paid operation; never trust only the displayed hash.
        from services.video_enhancement.media import file_digest
        import asyncio
        async with export_media.materialize(ref) as path:
            if await asyncio.to_thread(file_digest, path) != sha:
                raise HTTPException(409, localized_message('原片来源已变化，请重新准备成片'))
        params = await prepare_workflow({'operation': 'enhance_export', 'novel_id': source.novel_id,
            'chapter_id': source.chapter_id, 'source_video_id':source.source_video_id, 'team_id': ctx.team_id, 'user_id': ctx.user.id if ctx.user else None,
            'model_config_id': request.model_config_id, 'resolution': request.resolution,
            'source_export_id': source.id, 'source_sha256': sha, 'config_snapshot': quote['config_snapshot']})
        from models.ai_task import AiTask
        from services.ai_task_executor import ai_task_executor
        async with project_write(source.novel_id) as db:
            previous = await previous_submission(8, params, db)
            if previous:
                return await ChapterExport.get(task=previous), previous
            existing, identity = await self._enhancement(source, quote['recipe'], ctx, sha=sha)
            if existing and existing.task_id:
                task = await AiTask.get(id=existing.task_id).using_db(db)
                return existing, await bind_submission(task, params)
            export = await ChapterExport.create(novel_id=source.novel_id, chapter_id=source.chapter_id,
                source_video_id=source.source_video_id,
                team_id=ctx.team_id, created_by=ctx.user.id if ctx.user else None, parent_export_id=source.id,
                identity_key=identity, source_version=source.source_version, manifest=source.manifest,
                source_media_ref=ref, source_sha256=sha,
                source_probe=probe, recipe=quote['recipe'], using_db=db)
            task = await ai_task_executor.submit(AiTaskTypeEnum.video_enhancement, {**params, 'export_id': export.id}, db_connection=db)
            export.task_id = task.id
            await export.save(using_db=db, update_fields=['task_id'])
            return export, task

    async def configs(self, ctx):
        from services.model_resolution import resolve_scope_configs
        return await resolve_scope_configs(8, ctx.team_id,
            capability_filter=lambda row: row.api_protocol == 'volcengine_mediakit' and row.model == 'enhance-video-generative')

    async def apply_video(self, export_id: int, ctx: AuthContext):
        await require_roles('admin', 'creator')(ctx)
        export = await self.get(export_id, ctx)
        await require_generation_scope(export.novel_id, ctx.team_id)
        from services.video_enhancement.current_video import apply_enhanced_video
        video = await apply_enhanced_video(export, select=True)
        if video is None:
            raise ValueError(localized_message('请先选择已生成成功的视频'))
        return video

    async def describe(self, export: ChapterExport, selection: list[dict] | None = None) -> dict:
        from models.ai_task import AiTask
        task = await AiTask.get_or_none(id=export.task_id)
        if export.source_video_id is not None:
            selection = [{key:item.get(key) for key in ('scene_id','sequence','video_id')} for item in export.manifest]
        elif selection is None:
            from services.video_enhancement.sources import current_selection
            selection = await current_selection(export.chapter_id)
        recorded = [{key:item.get(key) for key in ('scene_id','sequence','video_id')} for item in export.manifest]
        from models.agent_operation import AgentOperation
        from models.scene import Scene
        operation = await AgentOperation.get_or_none(task_id=export.task_id, key='apply:enhanced_video', state='completed') if export.task_id else None
        result_video_id = operation.result.get('video_id') if operation else None
        applied_to_scene = False
        if result_video_id:
            scene = await Scene.get_or_none(id=operation.result['scene_id'], chapter_id=export.chapter_id)
            applied_to_scene = bool(scene and (scene.metadata or {}).get('current_video_id') == result_video_id)
        return {'id': export.id, 'chapter_id': export.chapter_id, 'source_video_id':export.source_video_id, 'parent_export_id': export.parent_export_id,
            'result_video_id': result_video_id, 'applied_to_scene': applied_to_scene,
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
