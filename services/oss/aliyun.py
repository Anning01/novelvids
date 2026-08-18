"""阿里云 OSS 提供方：零新增依赖，标准库实现 OSS V1 签名。

- 前端直传：POST 表单策略（policy base64 + HMAC-SHA1 签名）
- 服务端读写：Authorization 头签名（V1），默认走内网 endpoint 省流量
"""

import base64
import hashlib
import hmac
from email.utils import formatdate

import httpx

from services.oss.base import OSSProvider

_MAX_DIRECT_UPLOAD = 5 * 1024 * 1024 * 1024  # 直传策略默认上限 5GB


class AliyunProvider(OSSProvider):
    name = "aliyun"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        internal_endpoint: str,
        public_base: str,
        access_key_id: str,
        access_key_secret: str,
    ):
        self.bucket = bucket
        self.endpoint = endpoint
        self.internal_endpoint = internal_endpoint or endpoint
        self.public_base = (public_base or "").rstrip("/")
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret

    @property
    def enabled(self) -> bool:
        return bool(
            self.bucket
            and self.endpoint
            and self.access_key_id
            and self.access_key_secret
        )

    # ---- 公网访问地址 ----

    def public_url(self, key: str) -> str:
        if self.public_base:
            return f"{self.public_base}/{key}"
        return f"https://{self.bucket}.{self.endpoint}/{key}"

    # ---- 前端直传：POST 表单策略 ----

    def sign_form_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        max_size: int = _MAX_DIRECT_UPLOAD,
    ) -> dict:
        expiration = formatdate(usegmt=True)  # 占位（下面用 ISO 重新生成）
        policy = {
            "expiration": _iso_expiration(),
            "conditions": [
                {"bucket": self.bucket},
                ["starts-with", "$key", ""],
                ["starts-with", "$Content-Type", ""],
                ["content-length-range", 1, max_size],
            ],
        }
        policy_b64 = base64.b64encode(
            _json_bytes(policy)
        ).decode("ascii")
        signature = _hmac_sign(self.access_key_secret, policy_b64)
        return {
            # 直传必须使用 Bucket 虚拟主机域名（路径式已不再支持，POST 到
            # https://{bucket}.{endpoint}），CNAME 域名不支持 POST 表单上传。
            "url": f"https://{self.bucket}.{self.endpoint}",
            "fields": {
                "OSSAccessKeyId": self.access_key_id,
                "policy": policy_b64,
                "signature": signature,
                "key": key,
                "Content-Type": content_type,
            },
        }

    # ---- 服务端读写（内网） ----

    def _authorization(self, method: str, key: str, content_type: str = "") -> str:
        date = formatdate(usegmt=True)
        string_to_sign = (
            f"{method}\n\n{content_type}\n{date}\n/{self.bucket}/{key}"
        )
        signature = _hmac_sign(self.access_key_secret, string_to_sign)
        return date, f"OSS {self.access_key_id}:{signature}"

    def _internal_url(self, key: str) -> str:
        # 内网 endpoint 同样使用 Bucket 虚拟主机域名：
        # https://{bucket}.{internal_endpoint}/{key}
        return f"https://{self.bucket}.{self.internal_endpoint}/{key}"

    async def get_bytes(self, key: str) -> bytes:
        date, authorization = self._authorization("GET", key)
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(
                self._internal_url(key),
                headers={"Date": date, "Authorization": authorization},
            )
            response.raise_for_status()
            return response.content

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        date, authorization = self._authorization("PUT", key, content_type)
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.put(
                self._internal_url(key),
                content=data,
                headers={
                    "Date": date,
                    "Authorization": authorization,
                    "Content-Type": content_type,
                },
            )
            response.raise_for_status()


def _iso_expiration() -> str:
    from datetime import datetime, timedelta, timezone

    return (
        datetime.now(timezone.utc) + timedelta(minutes=15)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _json_bytes(payload: dict) -> bytes:
    import json

    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _hmac_sign(secret: str, message: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("ascii")
