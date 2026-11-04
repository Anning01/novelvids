"""Content validation shared by uploaded images and audio; no storage side effects."""
import asyncio
import mimetypes
import math
import subprocess
from pathlib import Path
from fastapi import HTTPException
from services.video.reference_media import _probe, _video_stream
from utils.messages import localized_message as msg


async def inspect_static_or_audio(path: Path, extension: str, kind: str, max_bytes: int) -> dict:
    size = path.stat().st_size
    if not 0 < size <= max_bytes:
        raise HTTPException(422, msg('素材大小超过服务端限制'))
    try:
        probe = await asyncio.to_thread(_probe, path)
        video = _video_stream(probe)
        audio = next((s for s in probe.get('streams', []) if s.get('codec_type') == 'audio'), None)
        duration = float(probe.get('format', {}).get('duration') or 0)
        if kind in {'image', 'sticker'}:
            expected = {'jpg': 'mjpeg', 'jpeg': 'mjpeg', 'png': 'png', 'webp': 'webp'}[extension]
            if video.get('codec_name') != expected or not video.get('width') or not 0 < video['width'] * video.get('height', 0) <= 32000000 or duration or int(video.get('nb_frames') or 1) > 1:
                raise ValueError('invalid static image')
        else:
            containers = set(probe.get('format', {}).get('format_name', '').split(','))
            expected = {'mp3': {'mp3'}, 'wav': {'wav'}, 'm4a': {'mov', 'mp4', 'm4a'}}[extension]
            if not audio or not math.isfinite(duration) or duration <= 0 or not containers.intersection(expected) or (video and not video.get('disposition', {}).get('attached_pic')):
                raise ValueError('invalid audio')
    except (HTTPException, ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise HTTPException(422, msg('无法读取素材，请检查文件格式和完整性')) from None
    return {'size_bytes': size, 'content_type': mimetypes.guess_type(f'file.{extension}')[0] or 'application/octet-stream',
            'duration': duration, 'width': video.get('width', 0), 'height': video.get('height', 0),
            'has_audio': bool(audio), 'codec': (audio or video).get('codec_name', ''), '_probe': probe}
