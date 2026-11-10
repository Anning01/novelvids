import base64

import httpx
import pytest

from services.image_generation.adapters import ImageGenerationInput, ImageProtocolAdapterError, image_protocol_adapter
from services.image_generation.gateway import ImageGenerationError, generate_images
from services.image_generation.uploads import image_uploads


@pytest.mark.parametrize("content,mime,extension", [
    (b"\xff\xd8\xffimage", "image/jpeg", "jpg"),
    (b"RIFF1234WEBPimage", "image/webp", "webp"),
])
async def test_uploads_detect_actual_file_type(content, mime, extension):
    async with httpx.AsyncClient() as client:
        uploads = await image_uploads(client, ("data:application/octet-stream;base64," + base64.b64encode(content).decode(),))
    assert uploads == [("image", (f"reference-1.{extension}", content, mime))]


@pytest.mark.parametrize("image", [{"url": "invalid"}, [None], [""]])
def test_openai_adapter_rejects_malformed_reference_list(image):
    with pytest.raises(ImageProtocolAdapterError, match="参考图片"):
        image_protocol_adapter("openai_compatible").prepare(
            ImageGenerationInput(model="custom", prompt="edit", extra_body={"image": image}))


@pytest.mark.parametrize("protocol,path", [("openrouter_compatible", "/images"), ("volcengine_ark", "/images/generations")])
def test_other_protocols_keep_json_references(protocol, path):
    prepared = image_protocol_adapter(protocol).prepare(ImageGenerationInput(
        model="custom", prompt="edit", extra_body={"image": ["https://cdn.example/ref.png"]}))
    assert prepared.path == path
    assert prepared.payload["image"] == ["https://cdn.example/ref.png"]
    assert prepared.images == ()


@pytest.mark.parametrize("source", ["data:image/png;base64,%%%", "data:image/png,raw", "data:image/png;base64,aGVsbG8="])
async def test_gateway_rejects_invalid_reference_before_provider_call(monkeypatch, source):
    async def handler(request):
        pytest.fail("Invalid images must not be submitted")

    real_client = httpx.AsyncClient
    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    with pytest.raises(ImageGenerationError, match="参考图片"):
        await generate_images(base_url="https://custom.example/v1", api_key="secret", model="custom",
            prompt="edit", extra_body={"image": source})


async def test_reference_download_failure_does_not_submit_edit(monkeypatch):
    async def handler(request):
        assert request.method == "GET"
        return httpx.Response(404)

    real_client = httpx.AsyncClient
    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    with pytest.raises(ImageGenerationError, match="网络请求失败"):
        await generate_images(base_url="https://custom.example/v1", api_key="secret", model="custom",
            prompt="edit", extra_body={"image": ["https://cdn.example/missing.png"]})
