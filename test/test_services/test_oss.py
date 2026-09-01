"""OSS 提供方与直传策略/终局端点测试。"""

import base64
import json

import pytest
from httpx import AsyncClient

from services.oss import make_upload_key
from services.oss.aliyun import AliyunProvider, _hmac_sign


# ---------------------------------------------------------------- 签名与 key


def test_aliyun_form_policy_contains_expected_fields():
    provider = AliyunProvider(
        bucket="my-bucket",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="oss-cn-beijing-internal.aliyuncs.com",
        public_base="",
        access_key_id="ak",
        access_key_secret="sk",
    )
    policy = provider.sign_form_upload(
        "uploads/0/20260818/abc-书稿.txt",
        "text/plain",
        20 * 1024 * 1024,
    )
    assert policy["url"] == "https://my-bucket.oss-cn-beijing.aliyuncs.com"
    fields = policy["fields"]
    assert fields["OSSAccessKeyId"] == "ak"
    assert fields["key"] == "uploads/0/20260818/abc-书稿.txt"
    # policy 可解出并满足 bucket/key 条件
    decoded = json.loads(base64.b64decode(fields["policy"]).decode("utf-8"))
    assert {"bucket": "my-bucket"} in decoded["conditions"]
    # 签名与 policy 匹配
    expected = _hmac_sign("sk", fields["policy"])
    assert fields["signature"] == expected


def test_aliyun_authorization_is_v1_format():
    provider = AliyunProvider(
        bucket="b",
        endpoint="e",
        internal_endpoint="i",
        public_base="",
        access_key_id="ak",
        access_key_secret="sk",
    )
    date, authorization = provider._authorization("PUT", "k.txt", "text/plain")
    assert authorization.startswith("OSS ak:")
    assert provider._internal_url("k.txt") == "https://b.i/k.txt"


@pytest.mark.asyncio
async def test_aliyun_put_bytes_persists_cache_control(monkeypatch):
    request: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *, timeout):
            request["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def put(self, url, *, content, headers):
            request.update(url=url, content=content, headers=headers)
            return FakeResponse()

    monkeypatch.setattr("services.oss.aliyun.httpx.AsyncClient", FakeClient)
    provider = AliyunProvider(
        bucket="b",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="oss-cn-beijing-internal.aliyuncs.com",
        public_base="https://cdn.example.com",
        access_key_id="ak",
        access_key_secret="sk",
    )

    await provider.put_bytes(
        "uploads/1/derivatives/cover-thumbnail.webp",
        b"webp",
        "image/webp",
        cache_control="public, max-age=31536000, immutable",
    )

    assert request["url"].startswith("https://b.oss-cn-beijing-internal")
    assert request["content"] == b"webp"
    assert request["headers"]["Content-Type"] == "image/webp"
    assert request["headers"]["Cache-Control"] == (
        "public, max-age=31536000, immutable"
    )


def test_public_url_is_public_read_no_signature():
    provider = AliyunProvider(
        bucket="b",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="i",
        public_base="https://cdn.example.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    url = provider.public_url("uploads/1/x.png")
    # Bucket 公共读：直接拼接公共域名，不带任何签名参数
    assert url == "https://cdn.example.com/uploads/1/x.png"
    assert "OSSAccessKeyId" not in url and "Expires=" not in url and "Signature" not in url


def test_make_upload_key_shape():
    key = make_upload_key(7, "我的 剧本!.txt")
    assert key.startswith("uploads/7/")
    assert key.endswith(".txt")
    assert " " not in key


def test_local_provider_disabled_by_default():
    from services.oss import oss

    # 默认环境（local）未启用直传
    assert oss.enabled is False


def test_resolve_media_url_local_passthrough():
    # LocalProvider（未启用 OSS）原样返回本地相对路径
    from services.oss import oss, resolve_media_url

    assert resolve_media_url("/media/assets/1.png") == "/media/assets/1.png"
    assert resolve_media_url("https://old-signed.example.com/x?Signature=dead") == (
        "https://old-signed.example.com/x?Signature=dead"
    )
    assert resolve_media_url(None) is None


def test_resolve_media_url_oss_builds_public_url_for_key():
    provider = AliyunProvider(
        bucket="b",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="i",
        public_base="https://cdn.example.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    url = provider.resolve_url("uploads/1/x.png")
    assert url == "https://cdn.example.com/uploads/1/x.png"
    assert "Expires=" not in url and "Signature" not in url


def test_resolve_media_url_oss_keeps_full_url():
    # 完整 URL（含历史签名/处理参数）与外部地址一律原样返回，不再重签
    provider = AliyunProvider(
        bucket="b",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="i",
        public_base="https://cdn.example.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    legacy = "https://cdn.example.com/uploads/1/x.png?Expires=1&Signature=old"
    assert provider.resolve_url(legacy) == legacy
    processed = "https://cdn.example.com/uploads/1/x.png?x-oss-process=image/resize,w_100"
    assert provider.resolve_url(processed) == processed
    assert provider.resolve_url("https://other-cdn.com/x.png") == (
        "https://other-cdn.com/x.png"
    )
    assert provider.resolve_url("/media/assets/1.png") == "/media/assets/1.png"


def test_normalize_media_url_local_passthrough():
    # 本地模式：原样返回
    from services.oss import normalize_media_url

    assert normalize_media_url("/media/assets/1.png") == "/media/assets/1.png"
    assert normalize_media_url(None) is None
    assert normalize_media_url("https://external.example.com/x.png") == (
        "https://external.example.com/x.png"
    )


def test_normalize_media_url_oss_downgrades_signed_url_to_key():
    # OSS 模式下：指向本桶的签名/完整 URL 落库前降级为 key；
    # 外部地址保持原样。
    provider = AliyunProvider(
        bucket="dramas-x",
        endpoint="oss-cn-guangzhou.aliyuncs.com",
        internal_endpoint="i",
        public_base="https://dramas-x.oss-cn-guangzhou.aliyuncs.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    signed = (
        "https://dramas-x.oss-cn-guangzhou.aliyuncs.com/"
        "uploads/0/20260819/x.png?OSSAccessKeyId=ak&Expires=1&Signature=old"
    )
    assert provider.normalize_media_ref(signed) == "uploads/0/20260819/x.png"
    assert provider.normalize_media_ref("uploads/0/20260819/x.png") == (
        "uploads/0/20260819/x.png"
    )
    assert provider.normalize_media_ref("/media/assets/1.png") == "/media/assets/1.png"
    assert provider.normalize_media_ref("https://other-cdn.com/x.png") == (
        "https://other-cdn.com/x.png"
    )
    assert provider.normalize_media_ref(None) is None


# ---------------------------------------------------------------- 端点


@pytest.mark.asyncio
async def test_upload_policy_direct_false_when_local(client: AsyncClient):
    response = await client.get(
        "/api/file/upload-policy",
        params={"filename": "剧本.txt", "content_type": "text/plain"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["direct"] is False


@pytest.mark.asyncio
async def test_upload_policy_direct_with_fake_provider(client, monkeypatch):
    from services.oss import base as oss_base
    from services.oss import oss as real_oss

    class FakeProvider(oss_base.OSSProvider):
        name = "fake"
        enabled = True

        def sign_form_upload(self, key, content_type, max_size):
            return {"url": "https://fake-oss/upload", "fields": {"key": key, "token": "t"}}

        def public_url(self, key):
            return f"https://fake-cdn/{key}"

    fake = FakeProvider()
    monkeypatch.setattr("api.file.oss", fake)
    response = await client.get(
        "/api/file/upload-policy",
        params={"filename": "剧本.txt", "content_type": "text/plain"},
    )
    data = response.json()["data"]
    assert data["direct"] is True
    assert data["provider"] == "fake"
    assert data["upload_url"] == "https://fake-oss/upload"
    assert data["fields"]["token"] == "t"
    assert data["public_url"].startswith("https://fake-cdn/")
    monkeypatch.setattr("api.file.oss", real_oss)


@pytest.mark.asyncio
async def test_oss_finalize_extracts_text_via_fake_provider(client, monkeypatch):
    from services.oss import base as oss_base

    class FakeProvider(oss_base.OSSProvider):
        name = "fake"
        enabled = True

        async def get_bytes(self, key):
            return "第一章 开端\n\n这是正文。".encode("utf-8")

        def public_url(self, key):
            return f"https://fake-cdn/{key}"

    fake = FakeProvider()
    monkeypatch.setattr("api.file.oss", fake)
    # oss_finalize 现经 services.document.analyze_oss_document 读取对象，需同步替换其 provider
    monkeypatch.setattr("services.document.oss", fake)
    response = await client.post(
        "/api/file/oss-finalize",
        json={"key": "uploads/0/20260818/x.txt", "original_filename": "剧本.txt"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "这是正文" in data["text_content"]
    assert data["chapter_validation"]["valid"] is True
    assert data["url"] == "https://fake-cdn/uploads/0/20260818/x.txt"
