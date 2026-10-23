"""独立资源文件的读写、探测与清理，不承担团队或目录规则。"""
import asyncio
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from config import settings
from services.oss import make_upload_key, normalize_media_url, oss
from services.video.reference_media import _probe, _video_stream, _fps, _positive_float


class ResourceStorage:
    formats = ("mp4", "mov")

    @property
    def max_bytes(self) -> int:
        return settings.RESOURCE_LIBRARY_MAX_SIZE_MB * 1024 * 1024

    def check_filename(self, filename: str) -> str:
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in self.formats:
            raise HTTPException(400, detail="资源库仅支持 MP4/MOV 视频")
        return extension

    def new_ref(self, team_id: int, filename: str) -> str:
        name = f"library-{uuid4().hex}-{Path(filename).name}"
        return make_upload_key(team_id, name) if oss.enabled else f"/media/resource-library/{team_id}/{name}"

    def local_path(self, ref: str) -> Path:
        root = Path(settings.MEDIA_PATH).resolve()
        if not ref.startswith("/media/"):
            raise HTTPException(400, detail="仅支持内部媒体文件")
        path = (root / ref.removeprefix("/media/")).resolve()
        if not path.is_relative_to(root):
            raise HTTPException(400, detail="媒体路径无效")
        return path

    @asynccontextmanager
    async def materialize(self, ref: str):
        ref = normalize_media_url(ref) or ref
        if ref.startswith("/media/"):
            path = self.local_path(ref)
            if not path.is_file():
                raise HTTPException(404, detail="视频文件不存在或已删除")
            yield path
        elif oss.enabled and ref.startswith("uploads/"):
            with TemporaryDirectory(prefix="resource-video-") as temporary:
                path = Path(temporary) / Path(ref).name
                await oss.download_to_file(ref, path)
                yield path
        else:
            raise HTTPException(400, detail="只允许当前团队内部视频，不支持外部链接")

    async def put(self, ref: str, path: Path, content_type: str) -> None:
        if ref.startswith("/media/"):
            destination = self.local_path(ref)
            destination.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copyfile, path, destination)
        else:
            await oss.put_file(ref, path, content_type)

    async def upload(self, ref: str, file: UploadFile) -> None:
        with TemporaryDirectory(prefix="resource-upload-") as temporary:
            path = Path(temporary) / "upload"
            size = 0
            with path.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise HTTPException(400, detail=f"视频不能超过 {settings.RESOURCE_LIBRARY_MAX_SIZE_MB}MB")
                    output.write(chunk)
            if not size:
                raise HTTPException(400, detail="视频文件为空")
            await self.put(ref, path, "video/quicktime" if self.check_filename(file.filename or "") == "mov" else "video/mp4")

    async def inspect(self, ref: str, filename: str) -> tuple[dict, str]:
        extension = self.check_filename(filename)
        async with self.materialize(ref) as path:
            size = path.stat().st_size
            if size > self.max_bytes or not size:
                raise HTTPException(400, detail=f"视频大小须在 1 字节至 {settings.RESOURCE_LIBRARY_MAX_SIZE_MB}MB 之间")
            probe = await asyncio.to_thread(_probe, path)
            stream = _video_stream(probe)
            duration = _positive_float(probe.get("format", {}).get("duration") or stream.get("duration"))
            containers = str(probe.get("format", {}).get("format_name", "")).split(",")
            if not {"mov", "mp4"}.intersection(containers) or not stream or not duration:
                raise HTTPException(400, detail="文件不是有效的 MP4/MOV 视频")
            media = {
                "content_type": "video/quicktime" if extension == "mov" else "video/mp4",
                "size_bytes": size, "width": int(stream.get("width") or 0),
                "height": int(stream.get("height") or 0), "duration": duration,
                "fps": _fps(stream), "codec": stream.get("codec_name", ""), "_probe": probe,
            }
            if not media["width"] or not media["height"]:
                raise HTTPException(400, detail="无法读取视频宽高")
            poster_ref = f"{ref}.poster.jpg"
            with TemporaryDirectory(prefix="resource-poster-") as temporary:
                poster = Path(temporary) / "poster.jpg"
                try:
                    await asyncio.to_thread(subprocess.run, [
                        "ffmpeg", "-v", "error", "-y", "-i", str(path),
                        "-frames:v", "1", "-vf", "scale=480:-2", str(poster),
                    ], check=True, capture_output=True, timeout=30)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise HTTPException(400, detail="无法读取视频画面") from exc
                await self.put(poster_ref, poster, "image/jpeg")
            return media, poster_ref

    async def delete(self, ref: str) -> None:
        if not ref:
            return
        if ref.startswith("/media/resource-library/"):
            await asyncio.to_thread(self.local_path(ref).unlink, missing_ok=True)
        elif oss.enabled and ref.startswith("uploads/") and "library-" in Path(ref).name:
            await oss.delete(ref)
        else:
            raise HTTPException(400, detail="拒绝删除非资源库文件")


resource_storage = ResourceStorage()
