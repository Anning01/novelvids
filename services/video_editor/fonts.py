"""Download only the selected, pinned font and share it between preview and export."""
import asyncio
import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

import httpx

from config import settings
from utils.messages import localized_message as msg
from utils.subtitle_fonts import FONT_REVISION, SUBTITLE_FONTS

_locks: dict[str, asyncio.Lock] = {}


async def cached_subtitle_font(font_id: str) -> Path:
    font = SUBTITLE_FONTS[font_id]
    suffix = Path(font['path']).suffix
    directory = Path(settings.CHAPTER_EXPORT_PATH).resolve() / '.subtitle-fonts'
    path = directory / f"{font_id}-{font['sha256']}{suffix}"
    async with _locks.setdefault(font_id, asyncio.Lock()):
        if path.is_file() and path.stat().st_size == font['size']:
            return path
        directory.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/wordshub/free-font/{FONT_REVISION}/{quote(font['path'])}"
        temporary = None
        try:
            async with httpx.AsyncClient(timeout=30) as client, client.stream('GET', url) as response:
                response.raise_for_status()
                with NamedTemporaryFile(dir=directory, delete=False) as target:
                    temporary = Path(target.name)
                    checksum = hashlib.sha256()
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > font['size']:
                            raise ValueError('Font exceeds pinned size')
                        checksum.update(chunk)
                        target.write(chunk)
            if size != font['size'] or checksum.hexdigest() != font['sha256']:
                raise ValueError('Font differs from pinned source')
            temporary.replace(path)
            return path
        except (httpx.HTTPError, OSError, ValueError):
            raise ValueError(msg('字幕字体加载失败，请稍后重试')) from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
