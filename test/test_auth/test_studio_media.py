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
from services.oss.studio_client import StudioMediaClient
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
    assert await policy(model_config_id=custom.id) is False
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_BASE_URL", "https://platform.example/v1")
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_API_KEY", "nv_test")
    assert await policy(model_config_id=custom.id) is False
    assert await policy() is False


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
    resolver=StudioMediaClient("https://platform.example/v1", key, team.id)
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
    third=await StudioMediaClient("https://platform.example/v1", key, team.id).resolve("data:image/png;base64,"+base64.b64encode(content).decode())
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


@pytest.mark.parametrize("protocol", ["volcengine_ark", "openrouter_compatible"])
async def test_direct_image_model_forwards_inline_without_platform_upload(monkeypatch, protocol):
    from services.image_generation.gateway import generate_images

    def unexpected_cat_client(*args, **kwargs):
        pytest.fail("Custom image models must not request Cat upload tickets")

    monkeypatch.setattr("services.oss.studio_client.studio_client", unexpected_cat_client)
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_API_KEY", "nv_platform")
    original = httpx.AsyncClient
    def vendor(req):
        assert req.url.host == "custom.example"
        assert req.headers["authorization"] == "Bearer nv_custom"
        assert json.loads(req.content)["image"] == ["data:image/png;base64,YQ=="]
        return httpx.Response(200, json={"data": [{"url": "https://custom.example/result.png"}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(vendor)))
    results = await generate_images(base_url="https://custom.example/v3", api_key="nv_custom",
        model="nv-custom", prompt="test", api_protocol=protocol, extra_body={"image": ["data:image/png;base64,YQ=="]})
    assert results[0].url.endswith("/result.png")


@pytest.mark.parametrize("use_oss", [False, True])
async def test_studio_sends_provider_file_to_selected_backend_only(tmp_path, monkeypatch, use_oss):
    from services.oss.studio_client import StudioMediaClient
    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path/"projects"))
    monkeypatch.setattr(settings, "STUDIO_MEDIA_CACHE_PATH", str(tmp_path/"cache"))
    root = tmp_path/"projects"
    root.mkdir()
    (root/"frame.png").write_bytes(b"frame")
    (root/"novel.txt").write_text("private novel")
    key = "1/" + "a"*32 + ".png"
    ref = "https://cat-media.invalid/studio-temporary/v1/"+key
    put = ("https://bucket.oss-cn-guangzhou.aliyuncs.com/studio-temporary/v1/" if use_oss
           else "https://cat.example/v1/media/temporary/")+key+"?signature=test"
    sent = []
    def dispatch(req):
        sent.append(req.method)
        if req.method == "POST":
            assert req.url.host == "cat.example"
            assert json.loads(req.content)["byte_length"] == 5
            return httpx.Response(200, json={"media_ref":ref, "upload_url":put,
                "headers":{"content-type":"image/png"}, "expires_at":4102444800})
        assert req.method == "PUT" and str(req.url) == put
        assert "authorization" not in req.headers and req.content == b"frame"
        return httpx.Response(204)
    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig(transport=httpx.MockTransport(dispatch), **kw))
    client = StudioMediaClient("https://cat.example/v1", "nv_test", 1)
    from services.video.base import VideoProviderError
    with pytest.raises(VideoProviderError):
        await client.resolve("/media/novel.txt")
    assert await client.resolve("https://user.example/image") == "https://user.example/image"
    assert await client.resolve("/media/frame.png") == ref
    assert await client.resolve("/media/frame.png") == ref
    assert sent == ["POST", "PUT"] and (root/"novel.txt").exists()



@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("failure", [None, "lease", "upload", "missing_ref", "disk_ticket"])
async def test_cat_generation_sends_only_uploaded_references(tmp_path, monkeypatch, kind, failure):
    from services.image_generation.gateway import generate_images, ImageGenerationError
    from services.video.base import VideoProviderError
    from services.video.unified import UnifiedVideoGenerator

    root = tmp_path / "media"
    root.mkdir()
    monkeypatch.setattr(settings, "MEDIA_PATH", str(root))
    monkeypatch.setattr(settings, "STUDIO_MEDIA_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    local_image = b"x" * (1024**2 + 1)
    (root / "second.png").write_bytes(local_image)
    public = "https://cdn.example/reference.png"
    images = ["data:image/png;base64,YQ==", public, "/media/second.png"]
    media = [("image/png", b"a"), ("image/png", local_image)]
    if kind == "video":
        media.extend([("video/mp4", b"video"), ("audio/mpeg", b"audio")])

    refs, uploads, submissions = [], [], []
    def dispatch(request):
        if request.url.path == "/v1/openapi.json":
            pytest.fail("Cat generation must not infer inline support from the ticket schema")
        if request.url.path == "/v1/studio/media-lease":
            index = len(refs)
            mime, content = media[index]
            assert request.headers["authorization"] == "Bearer nv_test"
            assert json.loads(request.content) == {
                "byte_length": len(content), "content_type": mime,
                "content_md5": base64.b64encode(md5(content, usedforsecurity=False).digest()).decode(),
            }
            extension = {"image/png":"png", "audio/mpeg":"mp3", "video/mp4":"mp4"}[mime]
            key = f"studio-temporary/v1/1/{index:032x}.{extension}"
            ref = "https://cat-media.invalid/" + key
            put = "https://test-bucket.oss-cn-guangzhou.aliyuncs.com/" + key
            refs.append(ref)
            if index == 1 and failure == "lease":
                return httpx.Response(503)
            ticket = {"upload_url": put + "?write=test", "headers": {"content-type": mime},
                      "media_ref": ref, "expires_at": 4102444800}
            if index == 1 and failure == "disk_ticket":
                ticket["upload_url"] = "https://cat.example/v1/media/temporary/" + key.split("/", 2)[2]
            if index == 1 and failure == "missing_ref":
                del ticket["media_ref"]
                ticket["read_url"] = put + "?read=test"
            return httpx.Response(200, json=ticket)
        if request.method == "PUT":
            assert request.url.host == "test-bucket.oss-cn-guangzhou.aliyuncs.com"
            assert "authorization" not in request.headers
            assert request.content == media[len(uploads)][1]
            uploads.append(request.content)
            return httpx.Response(503 if failure == "upload" and len(uploads) == 2 else 204)
        assert request.url.path == ("/v1/images/generations" if kind == "image" else "/v1/videos")
        submissions.append(request.content)
        assert request.headers["content-type"] == "application/json"
        assert b"data:" not in request.content and len(request.content) < 1024**2
        body = json.loads(request.content)
        expected = [refs[0], public, *refs[1:]]
        if kind == "image":
            assert body["image"] == expected
            return httpx.Response(200, json={"data":[{"url":"https://cdn.example/result.png"}]})
        assert [ref["url"] for ref in body["references"]] == expected
        assert [ref["type"] for ref in body["references"]] == ["image"] * 3 + ["video", "audio"]
        return httpx.Response(200, json={"id":"video-task"})

    original = httpx.AsyncClient
    def mock_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(dispatch)
        return original(**kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    config = dict(api_protocol="novelvids", base_url="https://cat.example/v1", api_key="nv_test", model="nv-test")
    if kind == "image":
        submit = generate_images(**config, prompt="test", extra_body={"image": images})
    else:
        generator = UnifiedVideoGenerator(AiModelConfig(**config, video_model_type="seedance_2"))
        submit = generator.submit(prompt="test", reference_images=images,
            reference_videos=["data:video/mp4;base64,dmlkZW8="], reference_audios=["data:audio/mp3;base64,YXVkaW8="])
    if failure:
        with pytest.raises(ImageGenerationError if kind == "image" else VideoProviderError) as caught:
            await submit
        assert not caught.value.submission_uncertain
        assert len(refs) == 2 and len(uploads) == (2 if failure == "upload" else 1)
        assert not submissions
    else:
        await submit
        assert len(uploads) == len(media) and len(submissions) == 1


async def test_generation_replaces_cached_legacy_read_url(tmp_path, monkeypatch):
    from services.oss.studio_client import StudioMediaClient

    monkeypatch.setattr(settings, "STUDIO_MEDIA_CACHE_PATH", str(tmp_path / "cache"))
    client = StudioMediaClient("https://cat.example/v1", "nv_test", None)
    source = "data:image/png;base64,YQ=="
    key = "studio-temporary/v1/1/" + "b" * 32 + ".png"
    obj = "https://test-bucket.oss-cn-guangzhou.aliyuncs.com/" + key
    ref = "https://cat-media.invalid/" + key
    requests = []
    def dispatch(request):
        requests.append(request.method)
        if request.method == "PUT":
            return httpx.Response(204)
        assert request.url.path.endswith("/studio/media-lease")
        ticket = {"upload_url": obj + "?write=test", "headers": {}, "expires_at": 4102444800}
        if len(requests) == 1:
            ticket["read_url"] = obj + "?read=test"
        else:
            ticket["media_ref"] = ref
        return httpx.Response(200, json=ticket)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(dispatch)))
    assert await client.resolve(source) == obj + "?read=test"
    assert await client.resolve_for_generation(source) == ref
    assert await client.resolve_for_generation(source) == ref
    assert requests == ["POST", "PUT", "POST", "PUT"]
