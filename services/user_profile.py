"""Self-service display name and validated avatar storage."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from auth.models import User
from config import settings
from services.oss import make_upload_key, oss
from services.video.reference_media import _probe
from utils.messages import localized_message as msg

MAX_AVATAR_BYTES = 5 * 1024 * 1024
_IMAGE_CODECS = {'png': ('.png', 'image/png'), 'mjpeg': ('.jpg', 'image/jpeg'), 'webp': ('.webp', 'image/webp')}


async def update_nickname(user: User, nickname: str) -> User:
    user.nickname = nickname
    await user.save(update_fields=['nickname', 'updated_at'])
    return user


async def update_avatar(user: User, file: UploadFile) -> User:
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if not data or len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(422, msg('头像图片不能为空且不能超过 5MB'))
    with TemporaryDirectory(prefix='novelvids-avatar-') as temporary:
        source = Path(temporary) / 'avatar'
        await asyncio.to_thread(source.write_bytes, data)
        probe = await asyncio.to_thread(_probe, source)
    image_format = (probe.get('format') or {}).get('format_name')
    streams = probe.get('streams') or []
    if image_format not in {'png_pipe', 'jpeg_pipe', 'webp_pipe', 'image2'} or len(streams) != 1 or streams[0].get('codec_name') not in _IMAGE_CODECS:
        raise HTTPException(422, msg('头像仅支持 JPG、PNG 或 WebP 图片'))
    width, height = streams[0].get('width', 0), streams[0].get('height', 0)
    if not (0 < width <= 6000 and 0 < height <= 6000):
        raise HTTPException(422, msg('头像图片宽高需在 1–6000 像素之间'))
    extension, content_type = _IMAGE_CODECS[streams[0]['codec_name']]
    filename = f'avatar-{user.id}-{uuid4().hex}{extension}'
    if oss.enabled:
        stored = make_upload_key(None, filename)
        await oss.put_bytes(stored, data, content_type)
    else:
        stored = '/media/avatars/' + filename
        destination = Path(settings.MEDIA_PATH) / 'avatars' / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, data)
    user.avatar_url = stored
    await user.save(update_fields=['avatar_url', 'updated_at'])
    return user
