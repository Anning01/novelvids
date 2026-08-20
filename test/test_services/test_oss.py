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


def test_public_url_is_signed_with_expiry():
    provider = AliyunProvider(
        bucket="b",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="i",
        public_base="https://cdn.example.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    url = provider.public_url("uploads/1/x.png")
    assert url.startswith("https://cdn.example.com/uploads/1/x.png?")
    assert "OSSAccessKeyId=ak" in url
    assert "Expires=" in url
    assert "Signature=" in url


def test_signed_url_signature_matches_v1_query_string():
    from urllib.parse import parse_qs, unquote, urlparse

    provider = AliyunProvider(
        bucket="b",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="i",
        public_base="",
        access_key_id="ak",
        access_key_secret="sk",
    )
    url = provider.signed_url("k/我.png", expires_seconds=3600)
    parsed = urlparse(url)
    assert parsed.hostname == "b.oss-cn-beijing.aliyuncs.com"
    query = parse_qs(parsed.query)
    expires = int(query["Expires"][0])
    signature = unquote(query["Signature"][0])
    # 重算签名，确保 URL 中的 Signature 与 OSS V1 查询串规则一致
    expected = _hmac_sign("sk", f"GET\n\n\n{expires}\n/b/k/我.png")
    assert signature == expected


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


def test_resolve_media_url_oss_signs_key():
    provider = AliyunProvider(
        bucket="b",
        endpoint="oss-cn-beijing.aliyuncs.com",
        internal_endpoint="i",
        public_base="https://cdn.example.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    url = provider.resolve_url("uploads/1/x.png")
    assert url.startswith("https://cdn.example.com/uploads/1/x.png?")
    assert "Expires=" in url and "Signature=" in url


def test_resolve_media_url_oss_keeps_full_url():
    # 历史遗留的已签名完整 URL 不参与重签，原样返回
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


def test_resolve_media_url_oss_signs_full_url_to_our_bucket():
    # 历史落库的“完整 URL 但无签名”应被识别为本桶对象并重新签发
    provider = AliyunProvider(
        bucket="dramas-x",
        endpoint="oss-cn-guangzhou.aliyuncs.com",
        internal_endpoint="i",
        public_base="https://dramas-x.oss-cn-guangzhou.aliyuncs.com",
        access_key_id="ak",
        access_key_secret="sk",
    )
    full = (
        "https://dramas-x.oss-cn-guangzhou.aliyuncs.com/"
        "uploads/0/20260819/27d5d75c00c5-asset-32_x.png"
    )
    url = provider.resolve_url(full)
    assert url.startswith(full + "?")
    assert "Expires=" in url and "Signature=" in url
    # 外部地址仍原样返回（不尝试签名）
    assert provider.resolve_url("https://other-cdn.com/x.png") == (
        "https://other-cdn.com/x.png"
    )


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
