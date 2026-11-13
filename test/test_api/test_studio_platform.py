import httpx
import pytest
import os
import subprocess
import sys

from config import settings
from models.config import AiModelConfig, StudioPlatformConnection
from services import studio_platform
from services.model_resolution import resolve_scope_configs


@pytest.mark.parametrize(("configured", "expected"), [
    ("", "https://shortdramas.xiazq.com/v1"),
    (" https://platform.example/ ", "https://platform.example/v1"),
])
def test_studio_platform_default_and_deployment_override(configured, expected):
    subprocess.run([sys.executable, "-c",
        "import sys; from services.studio_platform import platform_base_url; assert platform_base_url() == sys.argv[1]", expected],
        env={**os.environ, "STUDIO_PLATFORM_BASE_URL": configured}, check=True)


@pytest.mark.asyncio
async def test_studio_platform_connection_requires_super_admin(monkeypatch):
    from fastapi import FastAPI
    from auth.deps import AuthContext, get_auth_context
    from api.config import router

    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    app = FastAPI()
    app.include_router(router, prefix="/api/config")
    context = AuthContext()
    app.dependency_overrides[get_auth_context] = lambda: context
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for enabled in (False, True):
            monkeypatch.setattr(settings, "AUTH_ENABLED", enabled)
            for method, path in (("GET", ""), ("GET", "/account"), ("POST", "/sync"), ("PUT", "")):
                response = await client.request(method, "/api/config/studio-platform" + path, json={"api_key": "nv_test"})
                assert response.status_code == 403
        context.is_super_admin = True
        assert (await client.get("/api/config/studio-platform")).status_code == 200


@pytest.mark.asyncio
async def test_studio_sync_rotates_key_and_keeps_model_identity(client, monkeypatch):
    from auth.deps import AuthContext, get_auth_context
    from main import app
    monkeypatch.setitem(app.dependency_overrides, get_auth_context, lambda: AuthContext(is_super_admin=True))
    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_BASE_URL", "https://platform.example")
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_API_KEY", "")
    await StudioPlatformConnection.all().delete()
    models = [
        {"id": "nv-1", "name": "文本", "task_types": [1, 7], "tool_calls": True, "json_output": True},
        {"id": "nv-2", "name": "视频", "task_types": [4], "video_model_type": "seedance_2"},
    ]
    calls = []
    new_client = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        if request.headers["Authorization"] == "Bearer nv_invalid":
            return httpx.Response(401, json={"message": "nv_invalid"})
        return httpx.Response(200, json={"data": [
            {**model, "api_key": "provider-secret", "base_url": "https://supplier.example",
             "pricing": {"type": "text", "input_price_per_1m": 2, "output_price_per_1m": 4, "api_key": "provider-secret"}}
            for model in models
        ]})

    monkeypatch.setattr(studio_platform.httpx, "AsyncClient", lambda **kwargs: new_client(
        **kwargs, transport=httpx.MockTransport(respond)))
    path = "/api/config/studio-platform"
    assert (await client.get(path)).json()["data"] == {"connected": False}
    result = await client.put(path, json={"api_key": "nv_original"})
    assert result.json()["data"] == {"connected": True, "synced": 2}
    assert result.headers["cache-control"] == "no-store"
    assert str(calls[-1].url) == "https://platform.example/v1/models"
    assert calls[-1].headers["Authorization"] == "Bearer nv_original"
    assert "x-team-id" not in calls[-1].headers
    rows = await resolve_scope_configs(7, team_id=87)
    model = next(row for row in rows if row.scope == studio_platform.SYNC_SCOPE)
    assert model.api_key == "nv_original"
    assert model.pricing == {"type": "text", "currency": "CNY", "input_price_per_1m": 2, "output_price_per_1m": 4}
    assert model.base_url == "https://platform.example/v1" and model.supports_tool_calls
    for route in (path, "/api/config", f"/api/config/{model.id}"):
        response = await client.get(route)
        assert all(secret not in response.text for secret in ("provider-secret", "nv_original", "supplier.example"))
    assert (await client.patch(f"/api/config/{model.id}", json={"base_url": "https://other.example"})).json()["code"] == 409
    failed = await client.put(path, json={"api_key": "nv_invalid"})
    assert failed.json()["code"] == 422 and "nv_invalid" not in failed.text
    assert (await StudioPlatformConnection.get(id=1)).api_key == "nv_original"
    local_prices = {**model.pricing, "input_price_per_1m": 8}
    saved = await client.patch(f"/api/config/{model.id}", json={"pricing": local_prices})
    assert saved.json()["code"] == 0
    models.pop()
    assert (await client.put(path, json={"api_key": "nv_replacement"})).json()["data"]["synced"] == 1
    assert (await client.post(path + "/sync")).json()["data"]["synced"] == 1
    assert calls[-1].headers["Authorization"] == "Bearer nv_replacement"
    await model.refresh_from_db()
    assert model.api_key == "nv_replacement"
    assert model.pricing == local_prices
    assert not (await AiModelConfig.get(scope=studio_platform.SYNC_SCOPE, model="nv-2")).is_active
