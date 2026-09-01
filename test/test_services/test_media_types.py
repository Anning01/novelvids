import mimetypes

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from httpx import ASGITransport, AsyncClient
import pytest

from services.media_types import register_media_mime_types


@pytest.mark.asyncio
async def test_webp_static_file_uses_image_content_type_in_minimal_runtime(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delitem(mimetypes.types_map, ".webp", raising=False)
    register_media_mime_types()
    assert mimetypes.guess_type("thumbnail.webp")[0] == "image/webp"

    (tmp_path / "thumbnail.webp").write_bytes(b"webp")
    app = FastAPI()
    app.mount("/media", StaticFiles(directory=tmp_path), name="media")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.get("/media/thumbnail.webp")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
