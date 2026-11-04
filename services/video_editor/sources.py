"""Resolve typed, project-scoped source IDs; only managed media reaches FFmpeg."""
import asyncio
from fastapi import HTTPException
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from models.video_edit import EditorAsset
from schemas.video_edit import EditDocument, EditSource
from services.oss import normalize_media_url, resolve_media_url
from services.video_enhancement.media import file_digest
from services.video.reference_media import _probe, _video_stream, _fps
from utils.messages import localized_message as msg


def source_key(source: EditSource):
    return f'{source.kind}:{source.id}'


class EditSources:
    def __init__(self, novel_id: int, chapter_id: int):
        self.novel_id, self.chapter_id = novel_id, chapter_id

    async def resolve(self, source: EditSource) -> dict:
        key = source_key(source)
        if source.kind == 'missing':
            scene = await Scene.get_or_none(id=source.id, chapter_id=self.chapter_id)
            if not scene:
                raise HTTPException(404, msg('剪辑素材不存在或不属于当前项目'))
            return {'key': key, 'source': source.model_dump(), 'kind': 'video', 'missing': True,
                    'name': msg('分镜 {p0}', p0=scene.sequence), 'duration': scene.duration or 4}
        if source.kind == 'asset':
            asset = await EditorAsset.get_or_none(id=source.id, novel_id=self.novel_id)
            if not asset:
                raise HTTPException(404, msg('剪辑素材不存在或不属于当前项目'))
            return {'key': key, 'source': source.model_dump(), 'kind': asset.kind, 'name': asset.name,
                    'ref': asset.media_ref, 'url': resolve_media_url(asset.media_ref),
                    'poster': resolve_media_url(asset.poster_ref), 'sha256': asset.sha256, **asset.probe}
        if source.kind == 'library':
            from controllers.resource_library import resource_for
            novel = await Novel.get(id=self.novel_id).only('id', 'team_id')
            row = await resource_for(novel.team_id or 0, source.id, kind=None)
            if row.kind not in {'video', 'bgm', 'sound', 'sticker'}:
                raise HTTPException(422, msg('片段类型与素材类型不一致'))
            return {'key': key, 'source': source.model_dump(), 'kind': 'audio' if row.kind in {'bgm', 'sound'} else row.kind, 'library_kind': row.kind, 'name': row.name,
                    'ref': row.storage_ref, 'url': resolve_media_url(row.storage_ref),
                    'poster': resolve_media_url(row.poster_ref), **row.media}
        video = await Video.filter(id=source.id, scene__chapter__novel_id=self.novel_id,
                                   scene__deleted_at__isnull=True, status=3).select_related('scene').first()
        if not video or not video.url:
            raise HTTPException(404, msg('剪辑素材不存在或不属于当前项目'))
        data = video.metadata or {}
        return {'key': key, 'source': source.model_dump(), 'kind': 'video',
                'name': msg('分镜 {p0}', p0=video.scene.sequence),
                'scene_id': video.scene_id,
                'ref': normalize_media_url(video.url) or video.url, 'url': resolve_media_url(video.url),
                'poster': resolve_media_url(data.get('poster_thumbnail_url') or data.get('poster_url') or data.get('first_frame_url')),
                'duration': float(data.get('duration') or video.scene.duration or 4),
                'width': data.get('width', 0), 'height': data.get('height', 0), 'fps': data.get('fps', 24)}

    async def catalog(self):
        from services.video_enhancement.sources import current_selection
        items = []
        for row in await current_selection(self.chapter_id):
            source = EditSource(kind='video' if row['video_id'] else 'missing', id=row['video_id'] or row['scene_id'])
            item = await self.resolve(source)
            items.append({**item, 'sequence': row['sequence'], 'scene_id': row['scene_id']})
        for asset in await EditorAsset.filter(novel_id=self.novel_id).order_by('-id'):
            items.append(await self.resolve(EditSource(kind='asset', id=asset.id)))
        from models.resource_library import ProjectResource, VideoResource
        ids = await ProjectResource.filter(novel_id=self.novel_id).values_list('resource_id', flat=True)
        for resource in await VideoResource.filter(id__in=ids, state='ready', kind__in=['video','bgm','sound','sticker']):
            items.append(await self.resolve(EditSource(kind='library', id=resource.id)))
        return items

    async def validate(self, document: EditDocument, *, freeze=False):
        from config import settings
        if max((c.start + c.duration for c in document.clips), default=0) > settings.VIDEO_EDITOR_MAX_DURATION_SECONDS:
            raise HTTPException(422, msg('时间线超过服务端允许的时长'))
        # Bound simultaneous layers, not the number of sequential caption sentences.
        events = []
        for clip in document.clips:
            if clip.type in {'sticker', 'subtitle'}:
                start = round(clip.start * document.fps)
                end = start + max(1, round(clip.duration * document.fps))
                events.extend(((start, 1), (end, -1)))
        active = 0
        for _, change in sorted(events):
            active += change
            if active > settings.VIDEO_EDITOR_MAX_OVERLAYS:
                raise HTTPException(422, msg('叠加片段数量超过服务端限制'))
        if sum(c.type == 'audio' for c in document.clips) > settings.VIDEO_EDITOR_MAX_AUDIO_TRACKS:
            raise HTTPException(422, msg('音频片段数量超过服务端限制'))
        sources = {}
        for clip in document.clips:
            source = getattr(clip, 'source', None)
            if not source:
                continue
            key = source_key(source)
            if key not in sources:
                sources[key] = await self.resolve(source)
                if freeze:
                    if sources[key].get('missing'):
                        raise HTTPException(422, msg('片段 {p0} 的视频尚未生成', p0=clip.name or clip.id))
                    from services.video_editor.assets import editor_storage
                    async with editor_storage.materialize(sources[key]['ref']) as path:
                        raw = await asyncio.to_thread(_probe, path)
                        actual = _video_stream(raw)
                        probe = {'duration': float(raw.get('format', {}).get('duration') or 0),
                                 'width': actual.get('width', 0), 'height': actual.get('height', 0),
                                 'fps': _fps(actual) or document.fps,
                                 'has_audio': any(s.get('codec_type') == 'audio' for s in raw.get('streams', []))}
                        sha = await asyncio.to_thread(file_digest, path)
                        if sources[key].get('sha256') and sources[key]['sha256'] != sha:
                            raise HTTPException(409, msg('剪辑素材内容已变化，请重新读取'))
                        sources[key].update(probe, sha256=sha)
            item = sources[key]
            if item['kind'] != clip.type:
                raise HTTPException(422, msg('片段类型与素材类型不一致'))
            if item.get('missing'):
                continue
            if clip.type in {'video', 'audio'}:
                wanted = clip.source_end if clip.type == 'video' else clip.trim_in + clip.duration
                if not (clip.type == 'audio' and clip.loop) and wanted > float(item.get('duration', 0)) + .12:
                    raise HTTPException(422, msg('片段 {p0} 的裁剪范围超过原素材', p0=clip.name or clip.id))
                if clip.trim_in >= float(item.get('duration', 0)):
                    raise HTTPException(422, msg('片段 {p0} 的裁剪范围超过原素材', p0=clip.name or clip.id))
        return list(sources.values())


def public_media(item: dict):
    return {key: value for key, value in item.items() if key not in {'ref', 'sha256'}}
