"""阿里云 OSS 提供方：零新增依赖，标准库实现 OSS V1 签名。

- 前端直传：POST 表单策略（policy base64 + HMAC-SHA1 签名）
- 服务端读写：Authorization 头签名（V1），默认走内网 endpoint 省流量
- 公网访问：私有 Bucket 用带 Expires + Signature 的临时签名 URL
"""

import base64
import hashlib
import hmac
import time
from email.utils import formatdate
from urllib.parse import quote

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
        url_expires_seconds: int = 604800,
    ):
        self.bucket = bucket
        self.endpoint = endpoint
        self.internal_endpoint = internal_endpoint or endpoint
        self.public_base = (public_base or "").rstrip("/")
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.url_expires_seconds = int(url_expires_seconds or 604800)

    @property
    def enabled(self) -> bool:
        return bool(
            self.bucket
            and self.endpoint
            and self.access_key_id
            and self.access_key_secret
        )

    # ---- 公网访问地址 ----

    def signed_url(self, key: str, expires_seconds: int | None = None) -> str:
        """生成带过期时间与签名的临时访问 URL（私有 Bucket 用）。"""
        expires = int(time.time()) + int(expires_seconds or self.url_expires_seconds)
        # OSS V1 查询串签名：Signature = base64(HMAC-SHA1(Secret, "GET\n\n\n{Expires}\n/{Bucket}/{Key}"))
        string_to_sign = f"GET\n\n\n{expires}\n/{self.bucket}/{key}"
        signature = _hmac_sign(self.access_key_secret, string_to_sign)
        base = self.public_base or f"https://{self.bucket}.{self.endpoint}"
        return (
            f"{base}/{key}"
            f"?OSSAccessKeyId={quote(self.access_key_id, safe='')}"
            f"&Expires={expires}"
            f"&Signature={quote(signature, safe='')}"
        )

    def public_url(self, key: str) -> str:
        return self.signed_url(key)

    def resolve_url(self, raw: str | None) -> str | None:
        """把持久化的媒体地址解析为可访问 URL。

        落库时只存 OSS 对象 key（以 ``uploads/`` 开头）或完整 URL：
        - 裸 key：直接按当前时间重新签发；
        - 完整 URL 且指向本桶（与 ``public_base`` 或默认虚拟主机域名一致）：
          提取对象 key 后重新签发（兼容历史落库的完整 URL 与已过期的签名 URL，
          无需数据迁移）；query 中带非签名处理参数（如 ``x-oss-process``）时
          原样返回，避免破坏图片处理；
        - 其它完整 URL（外部地址）：原样返回，不做签名。
        """
        if not raw:
            return raw
        if raw.startswith("uploads/"):
            return self.signed_url(raw)
        if raw.startswith("http://") or raw.startswith("https://"):
            for base in self._public_bases():
                if raw.startswith(base + "/"):
                    path = raw[len(base) + 1 :]
                    key, query = _split_query(path)
                    if query and not _is_oss_signature_query(query):
                        # 带非签名处理参数（如 x-oss-process）的完整 URL 原样返回
                        return raw
                    return self.signed_url(key)
        return raw

    def _normalize_aliyun_url(self, raw: str) -> str:
        """把指向本桶的完整 URL 降级为对象 key（去掉 query 与域名前缀）。"""
        if raw.startswith("uploads/"):
            return raw
        if raw.startswith("http://") or raw.startswith("https://"):
            for base in self._public_bases():
                if raw.startswith(base + "/"):
                    key, _ = _split_query(raw[len(base) + 1 :])
                    if key.startswith("uploads/"):
                        return key
        return raw

    def _public_bases(self) -> list[str]:
        """本桶对外可能的公网基地址（用于识别完整 URL 是否指向本桶）。"""
        bases: list[str] = []
        if self.public_base:
            bases.append(self.public_base)
        bases.append(f"https://{self.bucket}.{self.endpoint}")
        bases.append(f"http://{self.bucket}.{self.endpoint}")
        # 去重并保持顺序
        seen: set[str] = set()
        result: list[str] = []
        for item in bases:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

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


def _split_query(path_and_query: str) -> tuple[str, str]:
    """把 "path?query" 拆成 (path, query)；无 query 时返回 ("",)。"""
    if "?" not in path_and_query:
        return path_and_query, ""
    path, query = path_and_query.split("?", 1)
    return path, query


def _is_oss_signature_query(query: str) -> bool:
    """判断 query 是否仅为 OSS V1 查询串签名参数（可安全丢弃并重新签发）。

    含 OSSAccessKeyId / Expires / Signature 的视为签名参数；若同时混有图片处理
    等其它参数（如 x-oss-process），则不能丢弃，返回 False 保持原样。
    """
    keys = {part.split("=", 1)[0] for part in query.split("&") if part}
    signature_keys = {"OSSAccessKeyId", "Expires", "Signature"}
    return bool(keys) and keys <= signature_keys


def _hmac_sign(secret: str, message: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("ascii")
