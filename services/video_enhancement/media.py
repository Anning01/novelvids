"""Materialize frozen sources and validate actual media, independently of submission."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from fastapi import HTTPException

from config import settings
from services.oss import oss, resolve_media_url
from services.resource_storage import ResourceStorage
from services.video.merge import video_merger
from services.video.reference_media import _probe, _video_stream, _fps
from services.video_enhancement.contract import MediaProbe
from utils.messages import localized_message


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def file_digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def inspect_media(path: Path) -> MediaProbe:
    try:
        raw = _probe(path)
        video = _video_stream(raw)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, HTTPException):
        raise ValueError(localized_message('无法读取成片视频，请检查文件是否完整')) from None
    return MediaProbe(duration=raw.get('format', {}).get('duration') or video.get('duration'),
        width=video.get('width'), height=video.get('height'), fps=_fps(video),
        color_transfer=video.get('color_transfer'), size=path.stat().st_size,
        audio_streams=[{key: stream.get(key) for key in ('codec_name', 'sample_rate', 'channels', 'channel_layout')}
            for stream in raw.get('streams', []) if stream.get('codec_type') == 'audio'])


class ExportMedia(ResourceStorage):
    def local_path(self, ref: str) -> Path:
        if ref.startswith('/media/exports/'):
            # Private exports live on the existing persistent data volume, outside StaticFiles.
            root = Path(settings.CHAPTER_EXPORT_PATH).resolve()
            if root.is_relative_to(Path(settings.MEDIA_PATH).resolve()):
                raise ValueError(localized_message('成片目录必须位于公开媒体目录之外'))
            path = (root / ref.removeprefix('/media/exports/')).resolve()
            if not path.is_relative_to(root):
                raise ValueError(localized_message('媒体路径无效'))
            return path
        return super().local_path(ref)

    def ref(self, export, name: str) -> str:
        prefix = f'uploads/{export.team_id or 0}/exports' if oss.enabled else '/media/exports'
        return f'{prefix}/{export.id}/{name}.mp4'

    async def store(self, ref: str, path: Path) -> None:
        if ref.startswith('/media/'):
            destination = self.local_path(ref)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=destination.parent, prefix='.export-') as temporary:
                staged = Path(temporary) / 'file.mp4'
                await asyncio.to_thread(shutil.copyfile, path, staged)
                os.replace(staged, destination)
        else:
            await self.put(ref, path, 'video/mp4')

    async def compose(self, export) -> dict:
        with TemporaryDirectory(prefix='chapter-export-') as directory:
            paths = []
            for index, item in enumerate(export.manifest):
                async with self.materialize(item['ref']) as source:
                    frozen = Path(directory) / f'{index}.mp4'
                    await asyncio.to_thread(shutil.copyfile, source, frozen)
                    if await asyncio.to_thread(file_digest, frozen) != item['sha256']:
                        raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
                    paths.append(str(frozen))
            if export.source_video_id is not None:
                output = Path(paths[0])
            else:
                output = Path(directory) / 'source.mp4'
                await asyncio.to_thread(video_merger.merge_paths, paths, str(output))
            probe = await asyncio.to_thread(inspect_media, output)
            sha = await asyncio.to_thread(file_digest, output)
            ref = self.ref(export, 'source')
            await self.store(ref, output)
            return {'ref': ref, 'sha256': sha, 'probe': probe.model_dump(mode='json')}

    def input_url(self, ref: str, media_base_url: str | None) -> str:
        if ref.startswith('/media/exports/'):
            raise ValueError(localized_message('本地成片通过 MediaKit 临时上传读取'))
        value = resolve_media_url(ref) or ''
        if value.startswith('/media/') and media_base_url:
            value = media_base_url.rstrip('/') + value
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(localized_message('请配置供应商可访问的 HTTPS 媒体地址'))
        return value

    async def save_enhanced(self, export, http) -> dict:
        url = (export.provider_result.get('result') or {}).get('video_url')
        parsed = urlsplit(url or '')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(localized_message('供应商未返回有效的增强视频地址'))
        with TemporaryDirectory(prefix='enhanced-export-') as directory:
            downloaded = Path(directory) / 'enhanced.mp4'
            async with http.stream('GET', url, follow_redirects=True) as response:
                response.raise_for_status()
                with downloaded.open('wb') as output:
                    async for block in response.aiter_bytes(1024 * 1024):
                        output.write(block)
            actual = await asyncio.to_thread(inspect_media, downloaded)
            from services.video_enhancement.contract import RESOLUTION_SHORT_SIDE
            resolution = (getattr(export, 'recipe', None) or {}).get('resolution', '1080p')
            source = MediaProbe.model_validate(export.source_probe)
            tolerance = max(2 / float(source.fps), .1)
            if (abs(float(actual.duration - source.duration)) > tolerance
                    or abs(actual.fps - source.fps) > .01
                    or abs(min(actual.width, actual.height) - RESOLUTION_SHORT_SIDE[resolution]) > 2
                    or actual.color_transfer in {'smpte2084', 'arib-std-b67'}
                    or abs(actual.width / actual.height / (source.width / source.height) - 1) > .01):
                raise ValueError(localized_message('增强视频的时长、比例或帧率与原片不符'))
            final = downloaded
            if source.audio_streams:
                async with self.materialize(export.source_media_ref) as original:
                    if await asyncio.to_thread(file_digest, original) != export.source_sha256:
                        raise ValueError(localized_message('原片来源已变化，请重新准备成片'))
                    final = Path(directory) / 'with-original-audio.mp4'
                    try:
                        await asyncio.to_thread(subprocess.run, ['ffmpeg', '-v', 'error', '-y',
                            '-i', str(downloaded), '-i', str(original), '-map', '0:v:0', '-map', '1:a',
                            '-c', 'copy', str(final)], check=True, capture_output=True, timeout=300)
                    except (OSError, subprocess.SubprocessError):
                        raise ValueError(localized_message('增强视频的声音或时序与原片不符')) from None
                actual = await asyncio.to_thread(inspect_media, final)
                if actual.audio_streams != source.audio_streams or abs(float(actual.duration - source.duration)) > tolerance:
                    raise ValueError(localized_message('增强视频的声音或时序与原片不符'))
            ref = self.ref(export, resolution)
            await self.store(ref, final)
            return {'ref': ref, 'sha256': await asyncio.to_thread(file_digest, final), 'probe': actual.model_dump(mode='json')}


export_media = ExportMedia()
