import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_workbench_capabilities(client: AsyncClient):
    response = await client.get("/api/workbench/capabilities")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "upload_media": True,
        "generate_asset": True,
        "generate_video": True,
        "apply_watermark": False,
        "compose_video": False,
    }
