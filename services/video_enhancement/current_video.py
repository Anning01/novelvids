"""Publish an enhanced clip as a recoverable video version, then select it once."""

from datetime import datetime, timezone
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.scene import Scene
from models.video import Video
from services.creation_agent.operation_receipts import record_once
from services.creation_objects import project_write
from services.video_enhancement.contract import MediaProbe, RESOLUTION_SHORT_SIDE
from services.video_enhancement.media import export_media, file_digest
from utils.messages import localized_message


APPLY_KEY = 'apply:enhanced_video'


async def apply_enhanced_video(export, *, select: bool = False) -> Video | None:
    if export.source_video_id is None:
        return None
    task = await AiTask.get(id=export.task_id)
    if task.status != 3 or not export.media_ref or not export.parent_export_id:
        raise ValueError(localized_message('请先选择已生成成功的视频'))
    source = await Video.get_or_none(id=export.source_video_id, scene__chapter_id=export.chapter_id,
                                     scene__chapter__novel_id=export.novel_id, scene__deleted_at__isnull=True)
    if source is None:
        if select:
            raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
        return None
    operation = await AgentOperation.get_or_none(task=task, key=APPLY_KEY, state='completed')
    if operation is None:
        import asyncio
        probe = MediaProbe.model_validate(export.output_probe)
        reported_seconds = (export.provider_result.get('result') or {}).get('duration')
        resolution = export.recipe.get('resolution', '1080p')
        if min(probe.width, probe.height) < RESOLUTION_SHORT_SIDE[resolution] - 2:
            raise ValueError(localized_message('增强视频的时长、比例或帧率与原片不符'))
        # Clips use ordinary video storage; the private export and original stay intact.
        ref = f'/media/videos/enhanced-{export.id}.mp4' if export.media_ref.startswith('/media/exports/') else export.media_ref
        async with export_media.materialize(export.media_ref) as path:
            if await asyncio.to_thread(file_digest, path) != export.media_sha256:
                raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
            if ref != export.media_ref:
                await export_media.store(ref, path)

        async def publish():
            async with project_write(export.novel_id):
                current_task = await AiTask.get(id=task.id)
                if current_task.status != 3:
                    raise ValueError(localized_message('请先选择已生成成功的视频'))
                scene = await Scene.get(id=source.scene_id)
                metadata = scene.metadata or {}
                chosen = metadata.get('current_video_id') or (metadata.get('workbench') or {}).get('activeVideoId')
                current = await Video.get_or_none(id=chosen, scene_id=scene.id) if chosen else await Video.filter(scene_id=scene.id).order_by('-id').first()
                same_source = current and (current.id == source.id or (current.metadata or {}).get('enhancement_source_video_id') == source.id)
                higher = not current or min(int((current.metadata or {}).get('width') or 0), int((current.metadata or {}).get('height') or 0)) < min(probe.width, probe.height)
                video = await Video.create(scene_id=scene.id, model_type=source.model_type, status=3, url=ref,
                    metadata={**{key: value for key, value in (source.metadata or {}).items()
                                 if key in {'poster_url', 'poster_thumbnail_url', 'first_frame_url', 'last_frame_url', 'ratio', 'aspect_ratio'}},
                        'enhancement_export_id': export.id, 'enhancement_source_video_id': source.id,
                        'width': probe.width, 'height': probe.height, 'fps': float(probe.fps),
                        'duration': float(probe.duration), 'resolution': resolution,
                        'provider_accounting': {'usage_reported': reported_seconds is not None,
                            'reported_seconds': float(reported_seconds) if reported_seconds is not None else None}})
                selected = False
                if select or same_source and higher:
                    selected = bool(await Scene.filter(id=scene.id, metadata=metadata).update(
                        metadata={**metadata, 'current_video_id': video.id}, updated_at=datetime.now(timezone.utc)))
                await AgentOperation.filter(task=task, key=APPLY_KEY).update(result={
                    'video_id': video.id, 'scene_id': scene.id, 'auto_selected': selected})

        await record_once(task.id, APPLY_KEY, publish)
        operation = await AgentOperation.get(task=task, key=APPLY_KEY)
    video = await Video.get(id=operation.result['video_id'])
    if select:
        from controllers.video import video_controller
        await video_controller.select_current(video.id)
    return video
