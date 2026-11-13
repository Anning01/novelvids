"""Exercise the public surface through the unmodified official SDK."""
import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from openai import APIStatusError, AsyncOpenAI

from api.platform import developer_router
from auth.deps import AuthContext
from auth.models import PlatformCallReceipt, Team, TeamMember, User
from config import settings
from models.config import AiModelConfig
from services.platform.access import create_key
from services.platform.http_contract import DEVELOPER_EXCEPTION_HANDLERS

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires platform authentication")
IMAGE = base64.b64encode(b"fixture image").decode()


@pytest.fixture
async def sdk_api(monkeypatch):
    user = await User.create(username="sdk-client", password_hash="!")
    team = await Team.create(name="SDK contract", balance=20)
    member = await TeamMember.create(user=user, team=team, role="creator")
    key = (await create_key(AuthContext(user=user, team_id=team.id, membership=member), "external"))["key"]
    common = dict(is_active=True, base_url="https://vendor.example/v1", api_key="upstream-fixture")
    text = await AiModelConfig.create(**common, name="Chat", model="official-chat", task_type=7,
        supports_tool_calls=True, supports_json_output=True,
        pricing={"type":"text", "input_price_per_1m":1, "output_price_per_1m":2})
    image = await AiModelConfig.create(**common, name="Image", model="official-image", task_type=2,
        api_protocol="openai_compatible", image_model_type="gpt_image_2",
        pricing={"type":"image", "prices":{"1K":0.2}})
    video = await AiModelConfig.create(**common, name="Video", model="official-video", task_type=4,
        api_protocol="volcengine_ark", video_model_type="seedance_2_5",
        pricing={"type":"video", "prices":{"720p":40}})
    app = FastAPI(exception_handlers=DEVELOPER_EXCEPTION_HANDLERS)
    app.include_router(developer_router, prefix="/v1")
    state = SimpleNamespace(seen=[], failure=None, stream=False)
    async def dispatch(req):
        if req.url.host == "platform.example":
            return await httpx.ASGITransport(app=app).handle_async_request(req)
        if req.url.host == "cdn.example":
            assert "authorization" not in req.headers
            return httpx.Response(200, content=b"video result", headers={"content-type":"video/mp4"})
        assert req.url.host == "vendor.example"
        assert req.headers["authorization"] == "Bearer upstream-fixture"
        await req.aread()
        state.seen.append(req)
        if state.failure:
            status, content, headers = state.failure
            return httpx.Response(status, content=content, headers=headers)
        if req.url.path.endswith("chat/completions"):
            return httpx.Response(200, json={"id":"chatcmpl-fixture", "object":"chat.completion", "created":1,
                "model":"official-chat", "choices":[{"index":0,"message":{"role":"assistant","content":None,
                "refusal":None,"tool_calls":[{"id":"tool-1","type":"function","function":{"name":"lookup","arguments":"{}"}}]},
                "finish_reason":"tool_calls","logprobs":None}], "usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12},
                "vendor_extension":{"kept":True}})
        if "/images/" in req.url.path:
            if state.stream:
                events = [{"type":"image_generation.partial_image", "b64_json":IMAGE,"partial_image_index":0},
                    {"type":"image_generation.completed", "b64_json":IMAGE, "created_at":1,"size":"1024x1024",
                    "quality":"high","background":"opaque","output_format":"png","usage":{"input_tokens":2,"output_tokens":2,"total_tokens":4}}]
                return httpx.Response(200, headers={"content-type":"text/event-stream"}, text="".join(
                    "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n" for event in events))
            return httpx.Response(200, json={"created":1,"data":[{"url":"https://cdn.example/result.png","revised_prompt":"kept"}],
                "background":"opaque", "usage":{"input_tokens":2,"output_tokens":2,"total_tokens":4}})
        if req.method == "POST":
            return httpx.Response(200, json={"id":"provider-video"})
        return httpx.Response(200, json={"status":"succeeded", "content":{"video_url":"https://cdn.example/video.mp4"},
            "duration":4, "usage":{"completion_tokens":10}})
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(dispatch)
    class RoutedClient(original_client):
        def __init__(self, **kwargs):
            super().__init__(**{"transport":transport, **kwargs})
    client_type = RoutedClient
    monkeypatch.setattr(httpx, "AsyncClient", RoutedClient)
    monkeypatch.setattr("services.platform.chat.provider_client", lambda config: AsyncOpenAI(api_key=config.api_key,
        base_url=config.base_url, max_retries=0, http_client=client_type(transport=transport)))
    async with AsyncOpenAI(api_key=key, base_url="https://platform.example/v1", max_retries=0,
        http_client=client_type(transport=transport, follow_redirects=True)) as sdk:
        yield sdk, state, (text, image, video)


async def test_chat_alias_and_official_optional_fields_are_lossless(sdk_api):
    sdk, state, _ = sdk_api
    response = await sdk.chat.completions.create(model="official-chat", messages=[
        {"role":"assistant","content":None,"tool_calls":[{"id":"previous","type":"function", "function":{"name":"lookup","arguments":"{}"}}]},
        {"role":"tool","content":"done","tool_call_id":"previous"}],
        store=False, metadata={"task":"sdk"}, modalities=["text"])
    sent = json.loads(state.seen[0].content)
    assert sent["store"] is False and sent["metadata"] == {"task":"sdk"}
    assert sent["messages"][0]["content"] is None
    assert response.choices[0].message.content is None
    assert response.model_extra["vendor_extension"] == {"kept":True}
    raw = response.model_dump(exclude_unset=True)
    assert "logprobs" in raw["choices"][0] and raw["choices"][0]["logprobs"] is None


async def test_sdk_image_generation_returns_urls_and_rejects_binary_edits(sdk_api):
    sdk, state, _ = sdk_api
    image = await sdk.images.generate(model="official-image", prompt="courtyard", size="1536x1024", background="opaque")
    assert image.data[0].url == "https://cdn.example/result.png" and image.data[0].revised_prompt == "kept"
    sent = json.loads(state.seen[-1].content)
    assert sent["size"] == "1536x1024" and sent["response_format"] == "url" and "quality" not in sent
    before = len(state.seen)
    with pytest.raises(APIStatusError) as rejected:
        await sdk.images.edit(model="official-image", prompt="change outfit", image=("face.png", b"source pixels", "image/png"))
    assert rejected.value.status_code == 400 and len(state.seen) == before


async def test_image_binary_streams_are_rejected_before_upstream(sdk_api):
    sdk, state, _ = sdk_api
    with pytest.raises(APIStatusError) as rejected:
        await sdk.images.generate(model="official-image", prompt="courtyard", stream=True, partial_images=1)
    assert rejected.value.status_code == 400 and not state.seen
    assert not await PlatformCallReceipt.all().exists()


async def test_sdk_video_create_retrieve_download(sdk_api):
    sdk, state, _ = sdk_api
    created = await sdk.videos.create(model="official-video", prompt="slow pan", seconds="4", size="1280x720")
    assert created.object == "video" and created.created_at > 0
    assert created.seconds == "4" and created.size == "1280x720" and created.model == "official-video"
    completed = await sdk.videos.retrieve(created.id)
    assert completed.status == "completed" and completed.progress == 100 and completed.completed_at
    content = await sdk.videos.download_content(created.id)
    assert await content.aread() == b"video result"
    assert (await PlatformCallReceipt.get()).state == "completed"


@pytest.mark.parametrize("endpoint", ["chat", "image", "video"])
@pytest.mark.parametrize("status", [400, 429, 503])
async def test_upstream_errors_are_returned_without_envelopes(sdk_api, endpoint, status):
    sdk, state, _ = sdk_api
    content = b'{ "error": {"code":"fixture_code", "message":"original provider message", "param":"prompt"}, "trace":"original" }'
    state.failure = status, content, {"content-type":"application/json", "x-request-id":"provider-trace", "retry-after":"7"}
    with pytest.raises(APIStatusError) as result:
        if endpoint == "chat":
            await sdk.chat.completions.create(model="official-chat", messages=[{"role":"user","content":"hello"}])
        elif endpoint == "image":
            await sdk.images.generate(model="official-image", prompt="courtyard")
        else:
            await sdk.videos.create(model="official-video", prompt="pan", seconds="4", size="1280x720")
    assert result.value.status_code == status
    assert result.value.response.content == content
    assert result.value.response.headers["retry-after"] == "7"
    assert result.value.response.headers["x-request-id"] == "provider-trace"
    assert (await PlatformCallReceipt.get()).state == ("review" if status >= 500 else "rejected")


async def test_public_validation_and_ai_guide(sdk_api):
    sdk, _, _ = sdk_api
    invalid = await sdk._client.post("https://platform.example/v1/chat/completions", json={"model":"missing","messages":[]})
    assert invalid.status_code == 401 and "error" in invalid.json() and "detail" not in invalid.json()
    missing = await sdk._client.get("https://platform.example/v1/unknown-route")
    assert missing.status_code == 404 and "error" in missing.json()
    guide = await sdk._client.get("https://platform.example/v1/agent-guide.md")
    assert guide.status_code == 200 and "text/markdown" in guide.headers["content-type"]
    assert "https://platform.example/v1" in guide.text
    for name in ("client.images.generate", "/media/uploads", "requests.put", "client.videos.create", "client.videos.retrieve", "client.videos.download_content", "error", "base_url"):
        assert name in guide.text


async def test_native_failed_video_payload_is_preserved(sdk_api):
    sdk, state, _ = sdk_api
    created = await sdk.videos.create(model="official-video", prompt="pan", seconds="4", size="1280x720")
    failure = {"code":"ProviderPolicyCode", "message":"original task failure", "param":"prompt"}
    state.failure = 200, json.dumps({"status":"failed", "error":failure}).encode(), {"content-type":"application/json"}
    failed = await sdk.videos.retrieve(created.id)
    assert failed.status == "failed"
    assert failed.error.model_dump(exclude_unset=True) == failure


async def test_video_uses_uploaded_url_and_rejects_multipart(sdk_api):
    sdk, state, _ = sdk_api
    with pytest.raises(APIStatusError) as rejected:
        await sdk.videos.create(model="official-video", prompt="pan", seconds="4", size="1280x720",
            input_reference=("reference.png", b"image pixels", "image/png"))
    assert rejected.value.status_code == 400 and not state.seen
    created = await sdk.videos.create(model="official-video", prompt="pan", seconds="4", size="1280x720",
        extra_body={"input_reference":"https://cdn.example/input.png"})
    assert created.object == "video"
    sent = json.loads(state.seen[-1].content)
    assert sent["content"][1]["image_url"]["url"] == "https://cdn.example/input.png"
    app = FastAPI()
    app.include_router(developer_router, prefix="/v1")
    body = app.openapi()["paths"]["/v1/videos"]["post"]["requestBody"]["content"]
    assert list(body) == ["application/json"]
    assert body["application/json"]["schema"]["properties"]["seconds"]["anyOf"][0]["type"] == "string"


async def test_secret_echo_is_redacted_without_rewriting_error(sdk_api):
    sdk, state, _ = sdk_api
    state.failure = 403, b'{"error":{"message":"invalid upstream-fixture", "code":"ExactCode"}}', {"content-type":"application/json"}
    with pytest.raises(APIStatusError) as result:
        await sdk.images.generate(model="official-image", prompt="pan")
    assert result.value.response.json() == {"error":{"message":"invalid [redacted]", "code":"ExactCode"}}


async def test_ambiguous_model_alias_never_selects_an_arbitrary_channel(sdk_api):
    sdk, state, models = sdk_api
    original = models[0]
    await AiModelConfig.create(name="other channel", model=original.model, task_type=7, is_active=True,
        base_url=original.base_url, api_key="not-used", pricing=original.pricing)
    with pytest.raises(APIStatusError) as result:
        await sdk.chat.completions.create(model=original.model, messages=[{"role":"user","content":"hello"}])
    assert result.value.status_code == 400 and not state.seen
    response = await sdk.chat.completions.create(model=f"nv-{original.id}", messages=[{"role":"user","content":"hello"}])
    assert response.model == f"nv-{original.id}"


async def test_url_video_retry_returns_original_task(sdk_api):
    sdk, state, _ = sdk_api
    params = dict(model="official-video", prompt="pan", seconds="4", size="1280x720",
        extra_body={"input_reference":"https://cdn.example/ref.png"}, extra_headers={"Idempotency-Key":"url-retry"})
    first = await sdk.videos.create(**params)
    second = await sdk.videos.create(**params)
    assert first.id == second.id and len(state.seen) == 1


@pytest.mark.parametrize("endpoint", ["chat/completions", "images/generations"])
async def test_http_200_business_errors_keep_original_body(sdk_api, endpoint):
    sdk, state, _ = sdk_api
    content = b'{"error":{"code":"BusinessFailure","message":"original business error"}}'
    state.failure = 200, content, {"content-type":"application/json"}
    body = {"model":"official-chat", "messages":[{"role":"user", "content":"hello"}]} if endpoint.startswith("chat") else {"model":"official-image", "prompt":"pan"}
    reply = await sdk._client.post("https://platform.example/v1/" + endpoint, json=body,
        headers={"authorization":"Bearer " + sdk.api_key})
    assert reply.status_code == 200 and reply.content == content
    receipt = await PlatformCallReceipt.get()
    assert receipt.state == "rejected" and reply.headers["x-novelvids-request-id"] == str(receipt.public_id)


async def test_external_api_key_gets_scoped_upload_metadata_without_file_proxy(sdk_api, monkeypatch):
    import hashlib
    from auth.models import StudioMediaLease
    from services.oss.temporary import TemporaryBucket
    sdk, _, _ = sdk_api
    monkeypatch.setattr("services.platform.temporary_media.bucket_config",
        lambda:TemporaryBucket("example-bucket", "cn-hangzhou", "fixture-access", "fixture-secret"))
    data = {"content_type":"image/png", "byte_length":123,
        "content_md5":base64.b64encode(hashlib.md5(b"pixels", usedforsecurity=False).digest()).decode()}
    reply = await sdk._client.post("https://platform.example/v1/media/uploads", json=data,
        headers={"authorization":"Bearer " + sdk.api_key})
    assert reply.status_code == 200
    ticket = reply.json()
    assert "x-oss-expires=172800" in ticket["read_url"] and "x-oss-expires=600" in ticket["upload_url"]
    assert "fixture-secret" not in reply.text and ticket["headers"]["content-length"] == "123"
    lease = await StudioMediaLease.get()
    assert "/" + str(lease.team_id) + "/" in lease.object_key


@pytest.mark.parametrize("inline", ["data:image/png;base64,AAAA", "data:video/mp4;base64,AAAA"])
async def test_inline_reference_is_rejected_before_any_provider_call(sdk_api, inline):
    sdk, state, _ = sdk_api
    with pytest.raises(APIStatusError) as error:
        await sdk.videos.create(model="official-video", prompt="pan", extra_body={"input_reference":inline})
    assert error.value.status_code == 422 and not state.seen


async def test_json_payload_is_bounded_even_without_content_length(sdk_api):
    sdk, state, _ = sdk_api
    async def chunks():
        yield b'{"model":"official-image","prompt":"'
        for _ in range(17):
            yield b"x" * (64 * 1024)
        yield b'"}'
    reply = await sdk._client.post("https://platform.example/v1/images/generations", content=chunks(),
        headers={"authorization":"Bearer " + sdk.api_key,"content-type":"application/json"})
    assert reply.status_code == 413 and not state.seen


async def test_upstream_inline_image_is_never_forwarded(sdk_api):
    sdk, state, _ = sdk_api
    state.failure = 200, json.dumps({"created":1,"data":[{"b64_json":IMAGE}]}).encode(), {"content-type":"application/json"}
    with pytest.raises(APIStatusError) as error:
        await sdk.images.generate(model="official-image", prompt="pan")
    assert error.value.status_code == 502 and IMAGE not in error.value.response.text
    assert (await PlatformCallReceipt.get()).state == "review"


async def test_direct_upload_then_url_generation_with_an_external_key(sdk_api, monkeypatch):
    import hashlib
    from services.oss.temporary import TemporaryBucket
    sdk, state, models = sdk_api
    image = models[1]
    await AiModelConfig.filter(id=image.id).update(api_protocol="volcengine_ark", image_model_type="seedream_5_pro",
        pricing={"type":"image", "prices":{"1.5K":0.2}})
    monkeypatch.setattr("services.platform.temporary_media.bucket_config",
        lambda:TemporaryBucket("example-bucket", "cn-hangzhou", "fixture-access", "fixture-secret"))
    pixels = b"direct upload fixture"
    uploaded = await sdk._client.post("https://platform.example/v1/media/uploads", json={"content_type":"image/png",
        "byte_length":len(pixels),"content_md5":base64.b64encode(hashlib.md5(pixels,usedforsecurity=False).digest()).decode()},
        headers={"authorization":"Bearer " + sdk.api_key})
    assert uploaded.status_code == 200
    ticket = uploaded.json()
    stored = []
    def oss(request):
        assert request.url.host == "example-bucket.oss-cn-hangzhou.aliyuncs.com"
        assert "authorization" not in request.headers
        assert request.headers["content-md5"] == ticket["headers"]["content-md5"]
        stored.append(request.content)
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(oss)) as storage:
        # This client is deliberately separate from the platform request transport.
        response = await storage.put(ticket["upload_url"], headers=ticket["headers"], content=pixels)
    assert response.status_code == 200 and stored == [pixels]
    result = await sdk.images.generate(model=image.model,prompt="reference",extra_body={"image":[ticket["read_url"]]})
    assert result.data[0].url == "https://cdn.example/result.png"
    sent = json.loads(state.seen[-1].content)
    assert sent["image"] == [ticket["read_url"]] and sent["response_format"] == "url"
    assert pixels not in state.seen[-1].content


@pytest.mark.parametrize("request_body", [
    {"model":"official-image","prompt":"pan","response_format":"b64_json"},
    {"model":"official-chat","messages":[{"role":"user","content":[{"type":"input_audio","input_audio":{"data":"AAAA","format":"wav"}}]}]},
    {"model":"official-chat","messages":[{"role":"user","content":"hello"}],"modalities":["text","audio"]},
])
async def test_base64_output_and_inline_audio_are_not_sent_upstream(sdk_api, request_body):
    sdk,state,_ = sdk_api
    endpoint = "images/generations" if request_body["model"] == "official-image" else "chat/completions"
    result = await sdk._client.post("https://platform.example/v1/" + endpoint, json=request_body,
        headers={"authorization":"Bearer " + sdk.api_key})
    assert result.status_code == 422 and not state.seen
    assert not await PlatformCallReceipt.all().exists()
