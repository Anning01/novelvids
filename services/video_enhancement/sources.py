"""Read and hash the exact selected chapter videos before creating an export."""

import asyncio

from models.scene import Scene
from models.video import Video
from services.video_enhancement.media import digest, export_media, file_digest, inspect_media
from services.oss import normalize_media_url
from utils.messages import localized_message


async def require_generation_scope(novel_id: int, team_id: int | None):
    from config import settings
    from fastapi import HTTPException
    from models.novel import Novel
    if settings.AUTH_ENABLED and (await Novel.get(id=novel_id)).team_id != team_id:
        raise HTTPException(403, localized_message('请先选择项目所属团队后再生成'))


async def current_selection(chapter_id: int) -> list[dict]:
    scenes = await Scene.filter(chapter_id=chapter_id).order_by('sequence')
    videos = await Video.filter(scene_id__in=[scene.id for scene in scenes], status=3).order_by('-id')
    selected = []
    for scene in scenes:
        metadata = scene.metadata or {}
        chosen = metadata.get('current_video_id') or (metadata.get('workbench') or {}).get('activeVideoId')
        video = next((video for video in videos if video.scene_id == scene.id and (chosen is None or chosen == video.id)), None)
        selected.append({'scene_id':scene.id,'sequence':scene.sequence,'video_id':video.id if video else None})
    return selected


async def freeze_video(video: Video, scene: Scene) -> tuple[list[dict], str]:
    if video.status != 3 or not video.url:
        raise ValueError(localized_message('请先选择已生成成功的视频'))
    ref = normalize_media_url(video.url) or video.url
    async with export_media.materialize(ref) as path:
        from services.video_enhancement.contract import require_upscale
        probe = await asyncio.to_thread(inspect_media, path)
        require_upscale(probe)
        sha = await asyncio.to_thread(file_digest, path)
    manifest = [{'scene_id':scene.id,'sequence':scene.sequence,'video_id':video.id,'ref':ref,'sha256':sha}]
    return manifest, digest({'video_id':video.id,'sha256':sha,'source_version':1})


async def freeze_chapter(chapter_id: int) -> tuple[list[dict], str]:
    scenes = await Scene.filter(chapter_id=chapter_id).order_by('sequence')
    manifest = []
    for scene in scenes:
        metadata = scene.metadata or {}
        workbench = metadata.get('workbench') or {}
        chosen = metadata.get('current_video_id') or workbench.get('activeVideoId')
        if chosen is not None:
            video = await Video.get_or_none(id=chosen, scene_id=scene.id, status=3)
        else:
            video = await Video.filter(scene_id=scene.id, status=3).order_by('-id').first()
        if video is None or not video.url:
            raise ValueError(localized_message('章节镜头尚未全部完成，无法准备高清成片'))
        ref = normalize_media_url(video.url) or video.url
        async with export_media.materialize(ref) as path:
            sha = await asyncio.to_thread(file_digest, path)
        manifest.append({'scene_id': scene.id, 'sequence': scene.sequence, 'video_id': video.id,
                         'ref': ref, 'sha256': sha})
    if not manifest:
        raise ValueError(localized_message('当前章节没有可导出的分镜'))
    # Re-read selection after I/O so a concurrent choice never silently changes this manifest.
    for item in manifest:
        scene = await Scene.get_or_none(id=item['scene_id'], chapter_id=chapter_id)
        if scene is None:
            raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
        metadata = scene.metadata or {}
        chosen = metadata.get('current_video_id') or (metadata.get('workbench') or {}).get('activeVideoId')
        latest = await Video.filter(scene_id=scene.id, status=3).order_by('-id').first() if chosen is None else None
        if scene.sequence != item['sequence'] or (chosen if chosen is not None else latest.id if latest else None) != item['video_id']:
            raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
    if await Scene.filter(chapter_id=chapter_id).count() != len(manifest):
        raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
    identities = [{key: item[key] for key in ('scene_id', 'sequence', 'video_id', 'sha256')} for item in manifest]
    return manifest, digest({'chapter_id': chapter_id, 'sources': identities, 'composition_version': 1})
