"""Durable opt-in continuation; all paid submissions use the normal export service."""
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from models.video import Video
from schemas.video_defaults import AutoEnhancement
from services.video_enhancement.contract import EnhancementOptions, EnhancementPricing, RESOLUTION_SHORT_SIDE
from utils.messages import localized_message

KEY = 'followup:auto_enhancement'
CONFIG_FIELDS = ('id', 'model', 'base_url', 'api_protocol', 'scope', 'team_id', 'processing_options', 'pricing')


def configuration_snapshot(config):
    values = {key: getattr(config, key) for key in CONFIG_FIELDS}
    values['processing_options'] = EnhancementOptions.model_validate(config.processing_options or {}).model_dump(mode='json')
    return values


def configuration_version(config):
    from services.video_enhancement.media import digest
    return digest(configuration_snapshot(config))


async def enhancement_snapshot(request: AutoEnhancement, team_id):
    from auth.deps import AuthContext
    from controllers.chapter_export import chapter_exports
    config = next((item for item in await chapter_exports.configs(AuthContext(team_id=team_id))
                   if item.id == request.model_config_id), None)
    if config is None:
        raise HTTPException(400, localized_message('增强服务不可用'))
    options = EnhancementOptions.model_validate(config.processing_options or {})
    if request.resolution not in options.output_resolutions:
        raise HTTPException(400, localized_message('增强服务未启用所选清晰度'))
    pricing = EnhancementPricing.model_validate(config.pricing or {})
    if not any(tier.short_side_max >= RESOLUTION_SHORT_SIDE[request.resolution] and tier.fps_max >= options.input_fps_min for tier in pricing.tiers):
        raise HTTPException(400, localized_message('所选高清化目标尚未配置价格'))
    if request.config_version and request.config_version != configuration_version(config):
        raise HTTPException(409, localized_message('增强配置已变化，请重新确认高清化'))
    return configuration_snapshot(config)


async def execution_context(params):
    from auth.deps import AuthContext, require_roles
    from auth.models import User, TeamMember
    from config import settings
    if not settings.AUTH_ENABLED:
        return AuthContext()
    user = await User.get_or_none(id=params.get('user_id'), status=1)
    membership = await TeamMember.filter(user_id=params.get('user_id'), team_id=params.get('team_id'),
        status=1, team__status=1).first()
    if user is None or (not user.is_super_admin and membership is None):
        raise HTTPException(403, localized_message('没有权限执行此操作'))
    ctx = AuthContext(user=user, membership=membership, team_id=params.get('team_id'), is_super_admin=user.is_super_admin)
    await require_roles('admin', 'creator')(ctx)
    return ctx


async def advance(operation):
    """One checkpoint at a time; restarting never repeats an external enhancement."""
    from controllers.chapter_export import chapter_exports
    from schemas.video_export import ExportEnhanceIn
    from services.balance import ensure_solvent
    parent = await AiTask.get(id=operation.task_id)
    params = parent.request_params
    video = await Video.get_or_none(id=params['video_id'])
    if video is None or parent.status in {4, 5} or video.status in {4, 5}:
        child_id = (operation.result or {}).get('enhancement_export_id')
        if child_id:
            from controllers.ai_task import ai_task_controller
            child = await ChapterExport.get(id=child_id)
            child_task = await AiTask.get(id=child.task_id)
            if child_task.status in {1, 2, 6}:
                await ai_task_controller.cancel(child.task_id)
        return {'stage': 'cancelled'}, True
    state = dict(operation.result or {})
    if video.status != 3 or (video.metadata or {}).get('billing_pending'):
        return state, False
    request = AutoEnhancement.model_validate(params['video_request']['auto_enhancement'])
    ctx = await execution_context(params)
    if state.get('enhancement_export_id'):
        enhanced = await chapter_exports.get(state['enhancement_export_id'], ctx)
        task = await AiTask.get(id=enhanced.task_id)
        if task.stage == 'billing_pending':
            return {**state, 'stage': 'enhancing'}, False
        if task.status in {3, 4, 5} or task.stage == 'needs_review':
            info = await chapter_exports.describe(enhanced)
            return {**state, 'stage': 'completed' if task.status == 3 else task.stage or 'failed',
                'result_video_id': info['result_video_id'], 'applied_to_scene': info['applied_to_scene'],
                'error': task.error_message}, True
        return {**state, 'stage': 'enhancing'}, False
    await ensure_solvent(ctx.team_id, params.get('user_id'))
    # Never accept a changed rate/service after the original generate confirmation.
    snapshot = await enhancement_snapshot(request, ctx.team_id)
    if snapshot != params.get('auto_enhancement_snapshot'):
        return {**state, 'stage': 'needs_confirmation', 'error': localized_message('增强配置已变化，请重新确认高清化')}, True
    if state.get('source_export_id'):
        source = await chapter_exports.get(state['source_export_id'], ctx)
    else:
        source, _ = await chapter_exports.prepare_video(video.id, ctx)
        state['source_export_id'] = source.id
    source_task = await AiTask.get(id=source.task_id)
    if source_task.status in {4, 5}:
        return {**state, 'stage': 'failed', 'error': source_task.error_message}, True
    if not source.source_sha256 or source_task.status != 3:
        return {**state, 'stage': 'preparing'}, False
    if min(source.source_probe.get('width', 0), source.source_probe.get('height', 0)) >= RESOLUTION_SHORT_SIDE[request.resolution]:
        return {**state, 'stage': 'skipped', 'error': localized_message('目标清晰度不高于原视频，已跳过增强')}, True
    quote = await chapter_exports.quote(source, request.model_config_id, ctx, request.resolution)
    enhanced, _ = await chapter_exports.enhance(source.id, ExportEnhanceIn(model_config_id=request.model_config_id,
        resolution=request.resolution, source_sha256=quote['source_sha256'], quote_version=quote['quote_version']), ctx,
        origin_task_id=parent.id)
    return {**state, 'stage': 'enhancing', 'enhancement_export_id': enhanced.id}, False


class AutomaticEnhancementRecovery:
    def __init__(self):
        self.jobs = {}

    async def start(self):
        # These receipts only orchestrate durable child tasks, never submit to a provider directly.
        await AgentOperation.filter(key=KEY, state='running', external=False).update(state='pending')

    async def step(self, operation):
        if not await AgentOperation.filter(id=operation.id, state='pending').update(state='running'):
            return
        done = False
        try:
            result, done = await advance(operation)
        except asyncio.CancelledError:
            await AgentOperation.filter(id=operation.id).update(state='pending')
            raise
        except HTTPException as error:
            result = {**(operation.result or {}), 'stage': 'needs_confirmation', 'error': error.detail}
            done = True
        except Exception as error:
            # A child export owns uncertainty and provider receipts. Do not resubmit on errors.
            result = {**(operation.result or {}), 'stage': 'failed', 'error': localized_message('自动高清化未完成，请查看高清化记录'),
                'error_type': type(error).__name__}
            done = True
        parent = await AiTask.get(id=operation.task_id)
        from services.creation_objects import project_write
        try:
            # Commit progress and the durable checkpoint together, preserving current media metadata.
            async with project_write(parent.request_params['novel_id']):
                await AgentOperation.filter(id=operation.id).update(state='completed' if done else 'pending', result=result,
                    updated_at=datetime.now(timezone.utc))
                video = await Video.get_or_none(id=parent.request_params.get('video_id'))
                if video:
                    video.metadata = {**(video.metadata or {}), 'auto_enhancement': result}
                    await video.save(update_fields=['metadata', 'updated_at'])
        except BaseException:
            await AgentOperation.filter(id=operation.id, state='running').update(state='pending')
            raise

    async def collect(self):
        for job in self.jobs.values():
            if job.done() and not job.cancelled():
                job.exception()  # Read checkpoint failures; pending receipts are retried below.
        self.jobs = {key: job for key, job in self.jobs.items() if not job.done()}
        for row in await AgentOperation.filter(key=KEY, state='pending').order_by('updated_at').limit(20):
            if row.id not in self.jobs and len(self.jobs) < 2:
                self.jobs[row.id] = asyncio.create_task(self.step(row))

    async def stop(self):
        for job in self.jobs.values(): job.cancel()
        await asyncio.gather(*self.jobs.values(), return_exceptions=True)


automatic_enhancements = AutomaticEnhancementRecovery()
