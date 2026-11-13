import asyncio
import base64
from datetime import datetime, timedelta, timezone
from hashlib import md5
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from api.platform import developer_router
from auth.deps import AuthContext
from auth.models import StudioMediaLease, Team, TeamMember, User
from config import settings
from models.config import AiModelConfig
from services.oss.temporary import TemporaryBucket
from services.platform.access import create_key
from services.platform.temporary_media import expire_uploads
from services.video.public_media import PublicMediaResolver
from test.test_auth import issue_test_session

PUT_HEADERS = {"content-type":"image/png", "content-length":"8", "content-md5":"bW9jay1jaGVja3N1bS0wMA==",
               "x-oss-object-acl":"private", "x-oss-forbid-overwrite":"true"}


@pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated user")
async def test_reference_upload_policy_prefers_local_for_studio_storage(client, monkeypatch):
    from unittest.mock import Mock

    user = await User.create(username="reference-upload-owner", password_hash="!")
    team = await Team.create(name="参考素材团队")
    await TeamMember.create(team=team, user=user, role="creator")
    headers = {"Authorization": "Bearer " + await issue_test_session(user.username), "X-Team-Id": str(team.id)}
    platform = await AiModelConfig.create(name="平台模型", model="nv-1", task_type=2,
        base_url="https://platform.example/v1", api_key="test", api_protocol="novelvids", is_active=True)
    custom = await AiModelConfig.create(name="自有模型", model="custom", task_type=4,
        base_url="https://custom.example/v1", api_key="test", is_active=True)
    oss = Mock(enabled=True)
    oss.name = "legacy-oss"
    oss.sign_form_upload.return_value = {"url": "https://legacy.example/upload", "fields": {}}
    oss.public_url.return_value = "https://legacy.example/reference.png"
    monkeypatch.setattr("api.file.oss", oss)
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_BASE_URL", "")
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_API_KEY", "")

    async def policy(**params):
        response = await client.get("/api/file/upload-policy", headers=headers,
            params={"filename": "reference.png", "content_type": "image/png", **params})
        return response.json()["data"]["direct"]

    assert await policy(model_config_id=platform.id) is False
    assert await policy(model_config_id=custom.id) is True
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_BASE_URL", "https://platform.example/v1")
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_API_KEY", "nv_test")
    assert await policy(model_config_id=custom.id) is False
    assert await policy() is True


@pytest.mark.parametrize("method,ttl,headers,expected", [
    ("GET",172800,{},"82bb3075ecd6b81faf65a9433b32dacdfeca8173cc849cabae61d637d23f28a1"),
    ("PUT",600,PUT_HEADERS,"8acb0c7a2f6232d1953bcd761f9820c8c480da3922c617c9fb0ebf02a21237ae"),
    ("DELETE",60,{},"2657de0d99176cc8aebeacc501b0bd5d7cf1c472e3420efadd923334e9036359"),
])
def test_v4_presign_matches_official_aliyun_sdk_vectors(method,ttl,headers,expected):
    # Expected signatures generated with Alibaba Cloud OSS Python SDK v2, SignerV4.
    bucket=TemporaryBucket("example-bucket","cn-hangzhou","test-id","test-secret")
    query=parse_qs(urlsplit(bucket.sign(method,"studio-temporary/v1/7/test.png",
        datetime(2026,1,1,tzinfo=timezone.utc),ttl,headers)).query)
    assert query["x-oss-signature"] == [expected] and query["x-oss-expires"] == [str(ttl)]


@pytest.mark.skipif(not settings.AUTH_ENABLED,reason="requires authenticated user")
async def test_studio_key_uploads_directly_reuses_refreshes_and_reclaims(monkeypatch,tmp_path):
    app=FastAPI()
    app.include_router(developer_router, prefix="/v1")
    route="/v1/studio/media-lease"
    assert route not in app.openapi()["paths"]
    user=await User.create(username="media-key-owner",password_hash="!")
    team=await Team.create(name="媒体团队")
    member=await TeamMember.create(team=team,user=user,role="creator")
    ctx=AuthContext(user=user,team_id=team.id,membership=member)
    general=(await create_key(ctx,"external"))["key"]
    key=(await create_key(ctx,"workspace",studio=True))["key"]
    content=b"local file content"
    check64=base64.b64encode(md5(content,usedforsecurity=False).digest()).decode()
    for k,v in {"STUDIO_PLATFORM_BASE_URL":"https://platform.example/v1","STUDIO_PLATFORM_API_KEY":key,
        "STUDIO_TEMP_BUCKET":"example-bucket","STUDIO_TEMP_REGION":"cn-hangzhou","OSS_ACCESS_KEY_ID":"test-id",
        "OSS_ACCESS_KEY_SECRET":"test-secret","MEDIA_PATH":str(tmp_path/"media"),"STUDIO_MEDIA_CACHE_PATH":str(tmp_path/"cache"),
        "DEPLOYMENT_ROLE":"studio"}.items():
        monkeypatch.setattr(settings,k,v)
    orig=httpx.AsyncClient
    backend=httpx.ASGITransport(app=app)
    async with orig(transport=backend,base_url="https://platform.example") as api:
        assert (await api.post(route,headers={"Authorization":"Bearer "+general},json={"content_type":"image/png",
            "byte_length":len(content),"content_md5":check64})).status_code==403
    objects={}
    posts=[]
    async def dispatch(req):
        if req.url.host=="platform.example":
            assert req.method=="POST" and req.url.path==route
            data=json.loads(await req.aread())
            assert data=={"content_md5":check64,"content_type":"image/png","byte_length":len(content)}
            assert req.headers["Authorization"]=="Bearer "+key
            posts.append(data)
            return await backend.handle_async_request(req)
        assert req.url.host=="example-bucket.oss-cn-hangzhou.aliyuncs.com" and "authorization" not in req.headers
        if req.method=="PUT":
            assert req.headers["x-oss-object-acl"]=="private" and req.headers["content-md5"]==check64
            assert int(req.headers["content-length"])==len(content) and req.url.params["x-oss-expires"]=="600"
            objects[req.url.path]=await req.aread()
            return httpx.Response(200)
        if req.method=="DELETE":
            objects.pop(req.url.path,None)
            return httpx.Response(204)
        assert req.method=="GET" and req.headers["range"]=="bytes=0-0"
        return httpx.Response(206 if req.url.path in objects else 404,content=b"x")
    monkeypatch.setattr(httpx,"AsyncClient",lambda *a,**kw: orig(*a,**kw,transport=httpx.MockTransport(dispatch)))
    source=tmp_path/"media"/"frame.png"
    source.parent.mkdir(); source.write_bytes(content)
    resolver=PublicMediaResolver(team_id=team.id)
    refs=await asyncio.gather(*(resolver.resolve("/media/frame.png") for _ in range(3)))
    assert len(set(refs))==1 and len(posts)==1
    assert parse_qs(urlsplit(refs[0]).query)["x-oss-expires"]==["172800"]
    assert list(objects.values())==[content] and source.read_bytes()==content
    cache,=(tmp_path/"cache").glob("*/*.json")
    original,=(cache.parent/"originals").iterdir()
    assert original.read_bytes()==content
    # Cloud deletion before URL expiry and URL expiry before cloud deletion are distinct.
    objects.clear()
    second=await resolver.resolve("/media/frame.png")
    assert second!=refs[0] and len(posts)==2
    data=json.loads(cache.read_text());data["expires_at"]=0;cache.write_text(json.dumps(data))
    third=await PublicMediaResolver(team_id=team.id).resolve("data:image/png;base64,"+base64.b64encode(content).decode())
    assert third!=second and len(posts)==3 and len(objects)==2
    await StudioMediaLease.filter(object_key=urlsplit(second).path.lstrip("/")).update(expires_epoch=int(datetime.now(timezone.utc).timestamp())-1)
    await expire_uploads()
    assert urlsplit(second).path not in objects and objects[urlsplit(third).path]==content
    assert original.read_bytes()==content


async def test_expiry_retries_storage_failure_without_deleting_other_objects(monkeypatch):
    from services.platform import temporary_media
    from unittest.mock import Mock
    monkeypatch.setattr(temporary_media, "bucket_config",lambda: TemporaryBucket("example-bucket","cn-hangzhou","test-id","test-secret"))
    now=datetime.now(timezone.utc)
    async def lease(name,expiry):
        return await StudioMediaLease.create(team_id=99, bucket="example-bucket",region="cn-hangzhou",
            object_key="studio-temporary/v1/99/"+name, byte_length=123, expires_epoch=int(expiry.timestamp()))
    past=await lease("expired.png",now-timedelta(seconds=1))
    future=await lease("recent.png",now+timedelta(hours=1))
    orig=httpx.AsyncClient
    storage=Mock(return_value=httpx.Response(503))
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:orig(**kw,transport=httpx.MockTransport(storage)))
    await expire_uploads()
    await past.refresh_from_db()
    assert past.retry_epoch > int(now.timestamp()) and await StudioMediaLease.filter(id=future.id).exists()
    storage.assert_called_once()
    await expire_uploads()
    storage.assert_called_once()
    await StudioMediaLease.filter(id=past.id).update(retry_epoch=int(now.timestamp()))
    storage.return_value=httpx.Response(404)
    await expire_uploads()
    assert not await StudioMediaLease.filter(id=past.id).exists() and await StudioMediaLease.filter(id=future.id).exists()


def test_signed_query_is_not_written_to_http_log():
    import logging
    from services.oss.temporary import redact_signed_urls
    url=httpx.URL("https://bucket.example/file?x-oss-signature=private-read-permission")
    record=logging.LogRecord("httpx", logging.INFO, "", 0, "HTTP Request: %s %s", ("GET",url),None)
    assert redact_signed_urls(record)
    assert record.getMessage()=="HTTP Request: GET https://bucket.example/file"


async def test_url_image_model_sends_direct_reference_without_inline_bytes(monkeypatch):
    from unittest.mock import AsyncMock
    from services.image_generation.gateway import generate_images
    from services.oss import studio_client as local
    reader=AsyncMock()
    reader.resolve.return_value="https://example.invalid/signed-file.png"
    monkeypatch.setattr(local,"studio_client",lambda *a,**kw:reader)
    original=httpx.AsyncClient
    def vendor(req):
        body=json.loads(req.content)
        assert body['image']==["https://example.invalid/signed-file.png"]
        assert b"base64" not in req.content
        return httpx.Response(200,json={"data":[{"url":"https://example.invalid/result.png"}]})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:original(**kw,transport=httpx.MockTransport(vendor)))
    results=await generate_images(base_url="https://example.invalid/v3",api_key="custom-test",model="model",prompt="test",
        api_protocol="volcengine_ark",extra_body={"image":["data:image/png;base64,YQ=="]})
    assert results[0].url.endswith("/result.png")
    reader.resolve.assert_awaited_once_with("data:image/png;base64,YQ==")
