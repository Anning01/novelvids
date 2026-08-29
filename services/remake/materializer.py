"""把受控重制来源解析为后台任务可读取的本地文件。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import settings
from services.oss import OSSProvider, oss


class RemakeMaterializationError(RuntimeError):
    pass


class RemakeMediaMaterializer:
    def __init__(
        self,
        *,
        media_root: str | Path | None = None,
        provider: OSSProvider = oss,
    ) -> None:
        self.media_root = Path(media_root or settings.MEDIA_PATH).resolve()
        self.provider = provider

    async def materialize(self, source: Any, work_dir: Path) -> Path:
        if source.storage_provider == "local":
            resolved = (self.media_root / str(source.object_key)).resolve()
            if not resolved.is_relative_to(self.media_root):
                raise RemakeMaterializationError("本地来源路径越界")
            if not resolved.is_file():
                raise RemakeMaterializationError("来源视频文件不存在")
            return resolved
        if source.storage_provider in {"oss", "aliyun"}:
            if not self.provider.enabled:
                raise RemakeMaterializationError("对象存储当前不可用")
            suffix = Path(str(source.original_filename)).suffix.lower()
            if suffix not in {".mp4", ".mov"}:
                suffix = ".mp4"
            work_dir.mkdir(parents=True, exist_ok=True)
            destination = work_dir / f"source{suffix}"
            try:
                await self.provider.download_to_file(str(source.object_key), destination)
            except Exception:
                destination.unlink(missing_ok=True)
                raise RemakeMaterializationError("下载来源视频失败") from None
            if not destination.is_file() or destination.stat().st_size <= 0:
                destination.unlink(missing_ok=True)
                raise RemakeMaterializationError("下载的来源视频为空")
            return destination
        raise RemakeMaterializationError(
            f"不支持的来源存储类型: {source.storage_provider}"
        )


remake_media_materializer = RemakeMediaMaterializer()
