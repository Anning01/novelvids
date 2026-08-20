"""对象存储抽象层。

- `local`：默认实现，不启用直传，所有存储继续走本地磁盘（行为不变）；
- `aliyun`：阿里云 OSS，前端直传（POST 表单策略），服务端经内网 endpoint 读写。
"""

import abc
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from config import settings


def make_upload_key(team_id: int | None, filename: str) -> str:
    """生成对象 key：uploads/{team}/{年月日}/{uuid}-{安全文件名}。"""
    safe_name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]", "_", Path(filename).name)[:80] or "file"
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"uploads/{team_id or 0}/{day}/{uuid4().hex[:12]}-{safe_name}"


class OSSProvider(abc.ABC):
    """对象存储提供方接口。"""

    name: str = ""

    @property
    def enabled(self) -> bool:
        return False

    def sign_form_upload(
        self, key: str, content_type: str, max_size: int
    ) -> dict:
        """签发浏览器直传所需信息：{url, fields}。"""
        raise NotImplementedError

    def public_url(self, key: str) -> str:
        raise NotImplementedError

    async def get_bytes(self, key: str) -> bytes:
        """服务端读取对象（应走内网 endpoint）。"""
        raise NotImplementedError

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        """服务端写入对象（应走内网 endpoint）。"""
        raise NotImplementedError

    def resolve_url(self, raw: str | None) -> str | None:
        """把持久化的媒体地址解析为可访问 URL。

        落库时只存 OSS 对象 key（以 ``uploads/`` 开头）或本地相对路径（以
        ``/media/`` 开头）；对外暴露时拼接公共读 URL：

        - 未启用 OSS（本地磁盘模式）：原样返回本地相对路径；
        - 已启用 OSS：对象 key 拼接公共读域名；完整 URL / 外部地址原样返回。
        """
        if not raw:
            return raw
        if self.enabled and raw.startswith("uploads/"):
            return self.public_url(raw)
        return raw

    def normalize_media_ref(self, raw: str | None) -> str | None:
        """落库前把媒体地址统一为持久化引用（OSS 下为对象 key）。

        前端可能直接提交完整 URL（历史行为），这里统一在写入前降级为 key；
        本地模式保持原样。
        """
        if not raw:
            return raw
        if self.enabled:
            return self._normalize_aliyun_url(raw)
        return raw

    def _normalize_aliyun_url(self, raw: str) -> str:
        return raw


class LocalProvider(OSSProvider):
    """本地磁盘模式：不启用直传，现有上传/存储链路保持不变。"""

    name = "local"


def _build_provider() -> OSSProvider:
    if settings.OSS_PROVIDER == "aliyun":
        from services.oss.aliyun import AliyunProvider

        return AliyunProvider(
            bucket=settings.OSS_BUCKET,
            endpoint=settings.OSS_ENDPOINT,
            internal_endpoint=settings.OSS_INTERNAL_ENDPOINT or settings.OSS_ENDPOINT,
            public_base=settings.OSS_PUBLIC_BASE,
            access_key_id=settings.OSS_ACCESS_KEY_ID,
            access_key_secret=settings.OSS_ACCESS_KEY_SECRET,
        )
    return LocalProvider()


oss: OSSProvider = _build_provider()


def resolve_media_url(raw: str | None) -> str | None:
    """对外暴露的媒体地址解析入口：落库存 key，读取时拼接公共读 URL。"""
    return oss.resolve_url(raw)


def normalize_media_url(raw: str | None) -> str | None:
    """落库前的媒体引用归一化入口：OSS 模式下把签名/完整 URL 降级为 key。

    供各 controller 在写库前统一调用，避免把有效期有限的签名 URL 持久化。
    """
    return oss.normalize_media_ref(raw)
