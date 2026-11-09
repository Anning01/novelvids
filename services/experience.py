"""Durable clip contexts over existing projects, agents, and media production."""
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from tortoise.transactions import in_transaction
from tortoise.exceptions import IntegrityError

from auth.deps import AuthContext, ensure_novel_access, ensure_project_creation_team
from controllers.config import ai_model_config_controller
from controllers.creation_agent import creation_agent_controller
from controllers.novel import novel_controller
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.asset import Asset
from prompts.experience import opening_message, with_references, render_named_references
from services.video.reference_media import reference_mention_syntax
from schemas.experience import ExperienceGenerateIn
from schemas.novel import NovelCreate
from schemas.creation_agent import AgentRunRequest
from schemas.agent_workflow import ProductionIntent
from services.creation_agent.skill_execution import require_agent
from services.experience_quote import require_clip_funds
from services.image_generation.capabilities import validate_selection as image_selection
from services.video.capabilities import validate_selection as video_selection
from utils.enums import AiTaskTypeEnum, AssetTypeEnum

CLIP_AUTHOR = '片段创作'


def _settings(project: Novel):
    if project.author != CLIP_AUTHOR:
        raise HTTPException(404, '片段不存在')
    try:
        data = json.loads(project.project_setting or '{}')
    except json.JSONDecodeError:
        raise HTTPException(404, '片段不存在') from None
    if not isinstance(data, dict) or not all(key in data for key in ('request_id', 'resolution', 'conversation_id')):
        raise HTTPException(404, '片段不存在')
    return data


async def clip_session(project_id: int, ctx: AuthContext):
    await ensure_novel_access(project_id, ctx)
    project = await Novel.get_or_none(id=project_id)
    if project is None:
        raise HTTPException(404, '片段不存在')
    data = _settings(project)
    chapter = await Chapter.get(novel_id=project.id, number=1)
    scene = await Scene.filter(chapter=chapter).order_by('sequence').first()
    asset = await Asset.filter(novel=project).order_by('id').first()
    return {**data, 'project_id': project.id, 'chapter_id': chapter.id,
            'scene_id': scene.id if scene else None, 'asset_id': asset.id if asset else None,
            'name': project.name, 'aspect_ratio': project.aspect_ratio,
            'resolution': data['resolution'], 'created_at': project.created_at}


async def create_clip(payload: ExperienceGenerateIn, ctx: AuthContext):
    ensure_project_creation_team(ctx)
    assistant, _ = await require_agent(ctx.team_id)
    task_type = AiTaskTypeEnum.video if payload.task_type == 'video' else AiTaskTypeEnum.reference_image
    config = await ai_model_config_controller.get_active(task_type.value, payload.model_config_id, team_id=ctx.team_id)
    if payload.task_type == 'video':
        selected = video_selection(config.video_model_type, api_protocol=config.api_protocol, generation_mode='reference', resolution=payload.resolution,
            aspect_ratio=payload.aspect_ratio, duration=payload.duration, output_format=None, generate_audio=None)
        resolution = selected.resolution
    else:
        selected = image_selection(config.image_model_type, clarity=payload.resolution, aspect_ratio=payload.aspect_ratio,
            output_format='png', generation_count=1)
        resolution = selected.clarity
    image_config = config if payload.task_type == 'image' else None
    if payload.mode == 'reference':
        image_config = await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image.value, team_id=ctx.team_id)
        image_selection(image_config.image_model_type, clarity=None, aspect_ratio=payload.aspect_ratio,
            output_format='png', generation_count=1)
    user_id = ctx.user.id if ctx.user else None
    key = 'clip:' + str(uuid5(NAMESPACE_URL, f'{ctx.team_id}:{user_id}:{payload.request_id}'))
    # Preserve idempotency hashes for clients created before named-reference support.
    serialized = payload.model_dump_json(exclude={'reference_binding'} if payload.reference_binding == 'all' else None)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    project = await Novel.get_or_none(creation_idempotency_key=key)
    if project is None:
        await require_clip_funds(payload, ctx, reference_image_config_id=image_config.id if payload.mode == 'reference' else None)
        try:
            async with in_transaction():
                project = await novel_controller.create(NovelCreate(
                    name=payload.prompt[:40], author=CLIP_AUTHOR, content=payload.prompt,
                    aspect_ratio=payload.aspect_ratio, resolution=resolution if payload.task_type == 'video' else None, total_chapters=1, storyboard_strategy='cinematic',
                    video_model_config_id=config.id if payload.task_type == 'video' else None,
                ), team_id=ctx.team_id, created_by=user_id)
                project.creation_idempotency_key = key
                project.creation_payload_hash = digest
                project.project_setting = json.dumps({
                    **payload.model_dump(mode='json'), 'resolution': resolution,
                    'model_name': config.name, 'assistant_model_config_id': assistant.id,
                    'image_model_config_id': image_config.id if image_config else None,
                }, ensure_ascii=False)
                await project.save(update_fields=['creation_idempotency_key', 'creation_payload_hash', 'project_setting'])
                chapter = await Chapter.create(novel=project, number=1, name='片段', content=payload.prompt)
                if payload.reference_binding == 'mentions':
                    source_prompt = render_named_references(payload.prompt, {
                        item.mention_name: reference_mention_syntax(item.type, item.mention_url or item.url)
                        for item in payload.reference_media
                    })
                    markers = []
                else:
                    source_prompt = payload.prompt
                    markers = [reference_mention_syntax(item.type, item.mention_url or item.url) for item in payload.reference_media]
                if payload.mode == 'reference':
                    markers.append('@{画面参考}')
                scene = None
                if payload.task_type == 'video':
                    scene = await Scene.create(chapter=chapter, sequence=1, description=payload.prompt[:120],
                        prompt=with_references(source_prompt, markers), duration=payload.duration,
                        metadata={'workbench': {'modelConfigId': config.id, 'aspectRatio': payload.aspect_ratio, 'resolution': resolution}})
                if image_config:
                    clarity = image_selection(image_config.image_model_type, clarity=resolution if payload.task_type == 'image' else None,
                        aspect_ratio=payload.aspect_ratio, output_format='png', generation_count=1).clarity
                    ref_image_urls = [item.url for item in payload.reference_media if item.type == 'image']
                    asset = await Asset.create(novel=project, asset_type=AssetTypeEnum.scene.value,
                        canonical_name='画面参考', base_traits=payload.prompt, description=payload.prompt,
                        is_global=False, source_chapters=[1],
                        metadata={
                            'aspect_ratio': payload.aspect_ratio,
                            'resolution': clarity,
                            'model_config_id': image_config.id,
                            'reference_images': ref_image_urls,
                        })
                    if scene is not None:
                        await scene.assets.add(asset)
                conversation = await creation_agent_controller.create(project.id, ctx)
                data = json.loads(project.project_setting)
                data['conversation_id'] = conversation.id
                project.project_setting = json.dumps(data, ensure_ascii=False)
                await project.save(update_fields=['project_setting'])
        except IntegrityError:
            project = await Novel.get_or_none(creation_idempotency_key=key)
            if project is None:
                raise
    if project.creation_payload_hash != digest:
        raise HTTPException(409, '该请求已创建片段，请使用新请求创建不同内容')
    return await clip_session(project.id, ctx)


async def start_clip(project_id: int, ctx: AuthContext, *, media_base_url: str = ""):
    session = await clip_session(project_id, ctx)
    mode = session['mode']
    if mode == 'direct':
        return await _start_direct(session, ctx, media_base_url=media_base_url)
    asset_id, scene_id = session['asset_id'], session['scene_id']
    intents = []
    request_id = uuid5(NAMESPACE_URL, f'clip-start:{project_id}:{session["request_id"]}')
    from models.creation_agent import AgentMessage
    if not await AgentMessage.filter(conversation_id=session['conversation_id'], request_id=request_id, role='user').exists():
        await require_clip_funds(ExperienceGenerateIn.model_validate({key: session[key] for key in ExperienceGenerateIn.model_fields if key in session}), ctx,
            reference_image_config_id=session.get('image_model_config_id'))
    if mode == 'reference':
        intents = [ProductionIntent(operation='image', target_id=asset_id,
            media_model_config_id=session['image_model_config_id'], request_id=uuid5(request_id, 'media'))]
    targets = ([{'kind': 'scene', 'id': scene_id}] if scene_id else []) + ([{'kind': 'asset', 'id': asset_id}] if asset_id else [])
    return await creation_agent_controller.submit(session['conversation_id'], AgentRunRequest(
        request_id=request_id, chapter_id=session['chapter_id'], model_config_id=session['assistant_model_config_id'],
        message=opening_message(mode=mode, task_type=session['task_type'], prompt=session['prompt'],
            scene_id=scene_id, asset_id=asset_id, aspect_ratio=session['aspect_ratio'], duration=session['duration']),
        targets=targets, write_scope='chapter', production_intents=intents), ctx)


async def _start_direct(session: dict, ctx: AuthContext, *, media_base_url: str):
    """Submit existing media jobs without asking an LLM to rewrite or dispatch."""
    from controllers.asset import asset_controller
    from controllers.video import video_controller
    from controllers._creation import creation_write
    from models.ai_task import AiTask
    from schemas.video import VideoGenerateRequest
    from services.creation_agent.production import conversation_for_task
    from services.creation_agent.submissions import submission, previous_submission

    request_id = uuid5(NAMESPACE_URL, f'clip-direct:{session["project_id"]}:{session["request_id"]}')
    token = submission.set({'submission_id': str(request_id), 'submission_hash': hashlib.sha256(str(request_id).encode()).hexdigest()})
    try:
        owner = {'team_id': ctx.team_id, 'user_id': ctx.user.id if ctx.user else None}
        task = await previous_submission(2 if session['task_type'] == 'image' else 4, owner)
        if task is None:
            await require_clip_funds(ExperienceGenerateIn.model_validate({key: session[key] for key in ExperienceGenerateIn.model_fields if key in session}), ctx)
            if session['task_type'] == 'image':
                ref_images = [item['url'] for item in session.get('reference_media', []) if item.get('type') == 'image']
                task = await asset_controller.reference(
                    session['asset_id'],
                    reference_images=ref_images or None,
                    media_model_config_id=session['model_config_id'],
                    **owner,
                )
            else:
                video = await video_controller.generate(VideoGenerateRequest(scene_id=session['scene_id'],
                    model_config_id=session['model_config_id'], request_id=request_id, aspect_ratio=session['aspect_ratio'],
                    resolution=session['resolution'], duration=session['duration'], reference_media=session['reference_media']), media_base_url=media_base_url, **owner)
                task = await AiTask.get(id=video.metadata['agent_run_id'])
        async with creation_write(session['project_id']):
            message = await conversation_for_task(task)
            project = await Novel.get(id=session['project_id'])
            data = _settings(project)
            data['conversation_id'] = message.conversation_id
            project.project_setting = json.dumps(data, ensure_ascii=False)
            await project.save(update_fields=['project_setting'])
        return task
    finally:
        submission.reset(token)
