"""Resolve model inputs against the Cat API upload contract selected by the server."""
import asyncio
import base64
import binascii
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import md5, sha256
from io import BytesIO
import json
import mimetypes
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

import httpx
from config import settings
from services.video.base import VideoProviderError
from services.oss.temporary import suppress_signed_queries

_locks = WeakValueDictionary()
BLOCK = 1024 * 1024


@dataclass(frozen=True)
class Original:
    path: Path
    content_type: str
    byte_length: int
    content_md5: str


@contextmanager
def open_source(source):
    if isinstance(source, Path):
        # Internal callers may upload private exports without publishing them under /media/.
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        file = source.open("rb")
    elif source.startswith("data:"):
        header, separator, encoded = source.partition(",")
        if not separator or not header.endswith(";base64"):
            raise VideoProviderError("参考素材编码无效")
        try:
            file = BytesIO(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error):
            raise VideoProviderError("参考素材编码无效") from None
        mime = header[5:-7]
    else:
        root = Path(settings.MEDIA_PATH).resolve()
        path = (root / source.removeprefix("/media/")).resolve()
        if not source.startswith("/media/") or not path.is_relative_to(root) or not path.is_file():
            raise VideoProviderError("本地参考素材不存在")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        file = path.open("rb")
    with file:
        yield mime, file


def inline_local_image(source):
    with open_source(source) as (mime, stream):
        if not mime.startswith("image/"):
            raise VideoProviderError("参考图需要图片文件")
        return f"data:{mime};base64," + base64.b64encode(stream.read()).decode()


def retain_original(source, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open_source(source) as (mime, stream):
        if mime.split("/", 1)[0] not in {"image", "video", "audio"}:
            raise VideoProviderError("仅模型使用的图片、视频和音频可申请临时上传")
        digest, checksum, count = sha256(), md5(usedforsecurity=False), 0
        with NamedTemporaryFile(dir=directory, delete=False) as file:
            temp = Path(file.name)
            try:
                while chunk := stream.read(BLOCK):
                    count += len(chunk)
                    digest.update(chunk)
                    checksum.update(chunk)
                    file.write(chunk)
                file.close()
                if count == 0:
                    raise VideoProviderError("参考素材为空")
                dest = directory / digest.hexdigest()
                if not dest.exists():
                    temp.replace(dest)
            finally:
                temp.unlink(missing_ok=True)
    return Original(dest, mime, count, base64.b64encode(checksum.digest()).decode())


async def file_chunks(path):
    with path.open("rb") as src:
        while chunk := await asyncio.to_thread(src.read, BLOCK):
            yield chunk


def trusted_object(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname and re.fullmatch(r"[a-z0-9-]+\.oss-[a-z0-9-]+\.aliyuncs\.com", parts.hostname) and parts.port in (443, None)
            and parts.path.startswith("/studio-temporary/v1/") and not parts.username and not parts.password)


class StudioMediaClient:
    def __init__(self, base_url, api_key, team_id):
        suppress_signed_queries()
        parts = urlsplit(base_url)
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or not (
            parts.scheme == "https" or parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise VideoProviderError("本地猫影的平台地址无效")
        self.base_url = base_url.rstrip("/")
        self.endpoint = self.base_url + "/studio/media-lease"
        self._inline_supported = None
        # Cat API accepts 16 MiB of JSON, including up to 1 MiB of metadata.
        self._inline_remaining = 15 * 1024**2
        self.api_key = api_key
        root = Path(settings.STUDIO_MEDIA_CACHE_PATH).resolve()
        if root.is_relative_to(Path(settings.MEDIA_PATH).resolve()):
            raise VideoProviderError("本地素材缓存需位于公开媒体目录之外")
        account = sha256(f"{self.endpoint}\0{api_key}\0{team_id}".encode()).hexdigest()
        self.directory = root / account

    def trusted_upload(self, url):
        if trusted_object(url):
            return True
        origin, target = urlsplit(self.endpoint), urlsplit(url)
        return (target.scheme == origin.scheme and target.netloc == origin.netloc
                and not target.fragment and re.fullmatch(
                    re.escape(origin.path.removesuffix("/studio/media-lease")) +
                    r"/media/temporary/[1-9][0-9]*/[a-f0-9]{32}\.[a-z0-9]{2,5}", target.path))

    @staticmethod
    def private_ref(value):
        return isinstance(value, str) and re.fullmatch(
            r"https://cat-media\.invalid/studio-temporary/v1/[1-9][0-9]*/[a-f0-9]{32}\.[a-z0-9]{2,5}", value)

    async def resolve_for_generation(self, source):
        """Old Cat API requires upload tickets even for an inline image or video."""
        if not isinstance(source, str) or not source.startswith("data:") or len(source) > self._inline_remaining:
            return await self.resolve(source)
        if self._inline_supported is None:
            try:
                async with httpx.AsyncClient(timeout=8, follow_redirects=False) as http:
                    reply = await http.get(self.base_url + "/openapi.json")
                    reply.raise_for_status()
                    props = reply.json()["components"]["schemas"]["UploadTicket"]["properties"]
                    self._inline_supported = isinstance(props, dict) and "media_ref" in props
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                # Upload tickets work with both generations and never submit a model task.
                self._inline_supported = False
        if self._inline_supported:
            self._inline_remaining -= len(source)
            return source
        return await self.resolve(source)

    async def resolve(self, source):
        if isinstance(source, str) and source.startswith(("https://", "http://")):
            return source
        obj = await asyncio.to_thread(retain_original, source, self.directory / "originals")
        identity = sha256((obj.path.name + "\0" + obj.content_type).encode()).hexdigest()
        cache = self.directory / (identity + ".json")
        lock = _locks.setdefault(str(cache), asyncio.Lock())
        try:
            async with lock, httpx.AsyncClient(timeout=300, follow_redirects=False) as http:
                if cache.exists():
                    try:
                        saved = json.loads(cache.read_text())
                    except (OSError, ValueError):
                        saved = {}
                    if not isinstance(saved, dict):
                        saved = {}
                    url = saved.get("url", "")
                    if saved.get("expires_at", 0) > time.time() + 60 and self.private_ref(url):
                        return url
                    if saved.get("expires_at", 0) > time.time() + 60 and trusted_object(url):
                        # GET signatures are method-specific. A range read checks the actual object.
                        async with http.stream("GET", url, headers={"Range":"bytes=0-0"}) as check:
                            if check.status_code in (200, 206):
                                return url
                            if check.status_code not in (403, 404, 410):
                                raise VideoProviderError("临时参考素材暂时无法读取，请重新上传")
                result = await http.post(self.endpoint, headers={"Authorization":"Bearer "+self.api_key}, json={
                    "content_type":obj.content_type, "byte_length":obj.byte_length, "content_md5":obj.content_md5})
                if result.status_code != 200:
                    raise VideoProviderError(f"平台未签发本地素材上传凭证（HTTP {result.status_code}）")
                ticket = result.json()
                put = ticket["upload_url"]
                get = ticket.get("media_ref") or ticket.get("read_url")
                if self.private_ref(get):
                    key = urlsplit(get).path.removeprefix("/studio-temporary/v1/")
                    valid = self.trusted_upload(put) and urlsplit(put).path.endswith("/" + key)
                else:
                    valid = (isinstance(get, str) and trusted_object(put) and trusted_object(get)
                             and put.partition("?")[0] == get.partition("?")[0])
                if not valid:
                    raise VideoProviderError("平台返回的临时素材地址无效")
                response = await http.put(put, headers=ticket["headers"], content=file_chunks(obj.path))
                if response.status_code not in (200, 201, 204):
                    raise VideoProviderError(f"参考素材直传失败（HTTP {response.status_code}）")
                with NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as file:
                    temporary = Path(file.name)
                    try:
                        json.dump({"url":get, "expires_at":int(ticket["expires_at"])},file)
                        file.close()
                        temporary.replace(cache)
                    finally:
                        temporary.unlink(missing_ok=True)
                return get
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise VideoProviderError("本地参考素材直传失败") from None


def studio_client(team_id, *, base_url=None, api_key=None):
    if settings.DEPLOYMENT_ROLE != "studio":
        return None
    if api_key and api_key.startswith("nv_") and base_url:
        return StudioMediaClient(base_url, api_key, team_id)
    if not base_url and not api_key and settings.STUDIO_PLATFORM_BASE_URL and settings.STUDIO_PLATFORM_API_KEY:
        return StudioMediaClient(settings.STUDIO_PLATFORM_BASE_URL, settings.STUDIO_PLATFORM_API_KEY, team_id)
    return None
