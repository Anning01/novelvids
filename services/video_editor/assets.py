"""Validated uploads for editing, kept separate from character voice references."""

from services.media_processing import run_media
import asyncio
import mimetypes
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from fastapi import HTTPException
from config import settings
from models.video_edit import EditorAsset
from services.oss import oss, make_upload_key
from services.resource_storage import ResourceStorage
from services.video_enhancement.media import export_media, file_digest
from services.video.reference_media import _probe, _video_stream, _fps
from services.video_editor.sources import EditSources, public_media
from utils.messages import localized_message as msg

FORMATS = {'video': ('mp4', 'mov'), 'audio': ('mp3', 'wav', 'm4a'), 'sticker': ('png', 'webp')}


class EditorStorage(ResourceStorage):
    @asynccontextmanager
    async def materialize(self, ref):
        if oss.enabled and ref.startswith('uploads/'):
            root = Path(settings.CHAPTER_EXPORT_PATH).resolve()
            root.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=root, prefix='.editor-source-') as directory:
                path = Path(directory) / 'source'
                await oss.download_to_file(ref, path)
                yield path
        else:
            async with export_media.materialize(ref) as path:
                yield path

    async def import_file(self, chapter, file, kind, ctx):
        extension = Path(file.filename or '').suffix.lower().lstrip('.')
        if kind not in FORMATS or extension not in FORMATS[kind]:
            raise HTTPException(422, msg('文件类型不符合所选素材分类'))
        root = Path(settings.CHAPTER_EXPORT_PATH).resolve()
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root, prefix='.editor-upload-') as directory:
            path, size = Path(directory) / f'input.{extension}', 0
            with path.open('wb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise HTTPException(413, msg('素材大小超过服务端限制'))
                    stream.write(chunk)
            if not size:
                raise HTTPException(422, msg('素材文件为空'))
            try:
                raw = await asyncio.to_thread(_probe, path)
            except (HTTPException, OSError, subprocess.SubprocessError, ValueError):
                raise HTTPException(422, msg('无法读取素材，请检查文件格式和完整性')) from None
            video = _video_stream(raw)
            audio = next((s for s in raw.get('streams', []) if s.get('codec_type') == 'audio'), None)
            duration = float(raw.get('format', {}).get('duration') or video.get('duration') or 0)
            if (kind == 'audio' and (not audio or duration <= 0)) or (kind == 'video' and (not video or duration <= 0)):
                raise HTTPException(422, msg('无法读取素材，请检查文件格式和完整性'))
            if kind == 'sticker' and (video.get('codec_name') not in {'png', 'webp'} or not video.get('width') or video.get('width', 0) * video.get('height', 0) > 32000000):
                raise HTTPException(422, msg('贴纸必须是有效的 PNG/WebP 静态图片'))
            if kind != 'sticker' and duration > settings.VIDEO_EDITOR_MAX_DURATION_SECONDS:
                raise HTTPException(422, msg('素材时长超过服务端限制'))
            # Reject animated image inputs: this editor's sticker timing is explicit and static.
            if kind == 'sticker' and raw.get('format', {}).get('duration'):
                raise HTTPException(422, msg('贴纸必须是有效的 PNG/WebP 静态图片'))
            novel_id = chapter.novel_id
            from models.novel import Novel
            team_id = (await Novel.get(id=novel_id).only('id', 'team_id')).team_id
            name = Path(file.filename or f'asset.{extension}').name[:255]
            filename = f'editor-{uuid4().hex}.{extension}'
            ref = make_upload_key(team_id, filename) if oss.enabled else f'/media/editor-assets/{novel_id}/{filename}'
            await self.put(ref, path, mimetypes.guess_type(name)[0] or 'application/octet-stream')
            probe = {'duration': duration, 'width': video.get('width', 0), 'height': video.get('height', 0),
                     'fps': _fps(video) if video else 0, 'has_audio': bool(audio)}
            poster_ref = None
            if kind == 'video':
                poster = Path(directory) / 'poster.jpg'
                await asyncio.to_thread(run_media, ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path),
                    '-frames:v', '1', '-vf', 'scale=480:-2', str(poster)], check=True, capture_output=True, timeout=30)
                poster_ref = ref + '.poster.jpg'
                await self.put(poster_ref, poster, 'image/jpeg')
            asset = await EditorAsset.create(novel_id=novel_id, team_id=team_id,
                created_by=ctx.user.id if ctx.user else None, kind=kind, name=name, media_ref=ref,
                poster_ref=poster_ref, probe=probe, sha256=await asyncio.to_thread(file_digest, path), size_bytes=size)
        from schemas.video_edit import EditSource
        return public_media(await EditSources(novel_id, chapter.id).resolve(EditSource(kind='asset', id=asset.id)))


editor_storage = EditorStorage()
