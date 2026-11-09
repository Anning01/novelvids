"""Validate and apply only video parameters, preserving all prompt/asset edits."""
from fastapi import HTTPException
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from schemas.video_defaults import VideoDefaults
from services.creation_objects import project_write
from services.video.capabilities import capabilities_for, validate_selection
from utils.messages import localized_message


async def validate_defaults(settings: VideoDefaults, team_id):
    from controllers.config import ai_model_config_controller
    config = await ai_model_config_controller.get_active(4, settings.model_config_id, team_id=team_id)
    caps = capabilities_for(config.video_model_type, config.api_protocol)
    validate_selection(config.video_model_type, api_protocol=config.api_protocol, generation_mode='reference', resolution=settings.resolution,
        aspect_ratio=settings.aspect_ratio, duration=caps.duration_min, return_last_frame=settings.return_last_frame,
        output_format=None, generate_audio=None)
    if settings.auto_enhancement:
        from services.video_enhancement.contract import RESOLUTION_SHORT_SIDE, resolution_short_side
        if (resolution_short_side(settings.resolution) or 0) >= RESOLUTION_SHORT_SIDE[settings.auto_enhancement.resolution]:
            raise HTTPException(422, localized_message('自动高清化目标必须高于生成分辨率'))
        from services.video_enhancement.automatic import enhancement_snapshot
        await enhancement_snapshot(settings.auto_enhancement, team_id)
    return config


async def apply_defaults(novel_id, request, ctx):
    from auth.deps import ensure_novel_access, require_roles
    await require_roles('admin', 'creator')(ctx)
    await ensure_novel_access(novel_id, ctx)
    novel = await Novel.get(id=novel_id)
    if not await Chapter.filter(id=request.chapter_id, novel_id=novel_id).exists():
        raise HTTPException(404, localized_message('章节不存在'))
    config = await validate_defaults(request.settings, novel.team_id)
    value = request.settings.model_dump(mode='json')
    async with project_write(novel_id) as db:
        scenes = await Scene.filter(chapter_id=request.chapter_id).using_db(db).select_for_update()
        for scene in scenes:
            mode = (scene.metadata or {}).get('video_generation_mode', 'reference')
            validate_selection(config.video_model_type, api_protocol=config.api_protocol, generation_mode=mode, resolution=value['resolution'],
                aspect_ratio=value['aspect_ratio'], duration=capabilities_for(config.video_model_type, config.api_protocol).duration_min,
                return_last_frame=value['return_last_frame'], output_format=None, generate_audio=None)
        for scene in scenes:
            scene.metadata = {**(scene.metadata or {}), 'video_model_config_id': value['model_config_id'],
                'video_resolution': value['resolution'], 'video_aspect_ratio': value['aspect_ratio'],
                'return_last_frame': value['return_last_frame'], 'auto_enhancement': value['auto_enhancement']}
            await scene.save(using_db=db, update_fields=['metadata', 'updated_at'])
        if request.remember:
            await Novel.filter(id=novel_id).using_db(db).update(video_generation_defaults=value,
                video_model_config_id=value['model_config_id'])
    return {'settings': value, 'scene_count': len(scenes), 'remembered': request.remember}
