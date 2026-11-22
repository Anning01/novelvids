import httpx
import pytest
import os
import subprocess
import sys

from config import settings
from models.config import AiModelConfig, StudioPlatformConnection
from services import studio_platform
from services.model_resolution import resolve_scope_configs


@pytest.mark.asyncio
async def test_studio_owner_can_toggle_synced_models_without_exposing_keys(monkeypatch):
    from fastapi import FastAPI
    from auth.deps import AuthContext, get_auth_context
    from api.config import router
    from unittest.mock import AsyncMock

    monkeypatch.setattr(settings, 'DEPLOYMENT_ROLE', 'studio')
    app = FastAPI()
    app.include_router(router, prefix='/api/config')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(is_super_admin=True)
    model = await AiModelConfig.create(name='Remote local switch', model='nv-901', task_type=7,
        task_types=[7], base_url='https://platform.example/v1', api_key='private-platform-key',
        scope=studio_platform.SYNC_SCOPE, is_active=True, supports_strict_output=True)
    monkeypatch.setattr(studio_platform, '_read_platform_catalog', AsyncMock(return_value=(None, None, None,
        studio_platform.Catalog(data=[{'id': 'nv-901', 'name': 'Remote', 'task_types': [7]}]))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        off = await client.post(f'/api/config/{model.id}/deactivate')
        assert off.status_code == 200, off.text
        assert off.json()['data']['is_active'] is False
        assert off.json()['data']['api_key'] is None
        assert 'private-platform-key' not in off.text
        await model.refresh_from_db()
        assert not model.local_enabled
        assert await resolve_scope_configs(7) == []
        on = await client.post(f'/api/config/{model.id}/activate')
        assert on.status_code == 200, on.text
        assert on.json()['data']['is_active'] is True and on.json()['data']['api_key'] is None
        await model.refresh_from_db()
        assert model.local_enabled
        assert [item.id for item in await resolve_scope_configs(7)] == [model.id]
        for method, body in [('PATCH', {'model': 'changed'}), ('DELETE', None)]:
            reply = await client.request(method, f'/api/config/{model.id}', json=body)
            assert reply.status_code == 409
        assert (await AiModelConfig.get(id=model.id)).model == 'nv-901'


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', [None, {'id': 'nv-901', 'name': 'Remote', 'task_types': [7], 'is_active': False},
    {'id': 'nv-901', 'name': 'Remote', 'task_types': [4], 'video_model_type': 'future_video'}])
async def test_local_activation_cannot_override_remote_unavailability(monkeypatch, entry):
    from fastapi import FastAPI
    from unittest.mock import AsyncMock
    from auth.deps import AuthContext, get_auth_context
    from api.config import router
    monkeypatch.setattr(settings, 'DEPLOYMENT_ROLE', 'studio')
    app = FastAPI()
    app.include_router(router, prefix='/api/config')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(is_super_admin=True)
    model = await AiModelConfig.create(name='Unavailable remote', model='nv-901', task_type=7,
        base_url='https://platform.example/v1', api_key='test-only', scope=studio_platform.SYNC_SCOPE,
        is_active=False, local_enabled=False)
    monkeypatch.setattr(studio_platform, '_read_platform_catalog', AsyncMock(return_value=(None, None, None,
        studio_platform.Catalog(data=[entry] if entry else []))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(f'/api/config/{model.id}/activate')
        assert response.status_code == 409
    await model.refresh_from_db()
    assert not model.is_active and not model.local_enabled


@pytest.mark.asyncio
@pytest.mark.parametrize('super_admin,deployment_role,expected', [(False, 'studio', 403), (True, 'platform', 404)])
async def test_synced_model_toggle_keeps_studio_super_admin_boundary(monkeypatch, super_admin, deployment_role, expected):
    from fastapi import FastAPI
    from auth.deps import AuthContext, get_auth_context
    from api.config import router
    from auth.models import Team, TeamMember, User
    monkeypatch.setattr(settings, 'AUTH_ENABLED', True)
    monkeypatch.setattr(settings, 'DEPLOYMENT_ROLE', deployment_role)
    app = FastAPI()
    app.include_router(router, prefix='/api/config')
    user = await User.create(username='toggle-admin', is_super_admin=super_admin)
    team = await Team.create(name='Toggle team')
    membership = await TeamMember.create(user=user, team=team, role='admin')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user, membership=membership, is_super_admin=super_admin, team_id=team.id)
    model = await AiModelConfig.create(name='Protected remote', model='nv-902', task_type=7,
        base_url='https://platform.example/v1', api_key='test-only', scope=studio_platform.SYNC_SCOPE, is_active=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for action in ('activate', 'deactivate'):
            reply = await client.post(f'/api/config/{model.id}/{action}')
            assert reply.status_code == expected
    await model.refresh_from_db()
    assert model.is_active


@pytest.mark.asyncio
async def test_sync_preserves_local_switch_through_refresh_and_key_rotation(monkeypatch):
    from controllers.config import ai_model_config_controller
    monkeypatch.setattr(settings, 'STUDIO_PLATFORM_BASE_URL', 'https://platform.example')
    catalog = {'data': [{'id': 'nv-901', 'name': 'Remote', 'task_types': [7], 'strict_output': True}]}
    original_client = httpx.AsyncClient
    monkeypatch.setattr(studio_platform.httpx, 'AsyncClient', lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=catalog))))
    await studio_platform.sync_platform_models('nv_initial')
    model = await AiModelConfig.get(scope=studio_platform.SYNC_SCOPE, model='nv-901')
    await ai_model_config_controller.deactivate(model.id)
    catalog['data'][0]['concurrency'] = 4
    catalog['data'].append({'id': 'nv-902', 'name': 'New remote', 'task_types': [7], 'strict_output': True})
    await studio_platform.sync_platform_models('nv_replacement')
    await studio_platform.sync_platform_models()
    await model.refresh_from_db()
    assert not model.local_enabled and not model.is_active
    assert model.api_key == 'nv_replacement' and model.concurrency == 4
    added = await AiModelConfig.get(scope=studio_platform.SYNC_SCOPE, model='nv-902')
    assert added.local_enabled and added.is_active
    assert [item.id for item in await resolve_scope_configs(7)] == [added.id]
    await ai_model_config_controller.activate(model.id)
    await studio_platform.sync_platform_models()
    await model.refresh_from_db()
    assert model.local_enabled and model.is_active


@pytest.mark.parametrize(("configured", "expected"), [
    ("", None),
    (" https://platform.example/ ", "https://platform.example/v1"),
])
def test_studio_platform_default_and_deployment_override(configured, expected):
    subprocess.run([sys.executable, "-c",
        "import sys; from config import settings; from services.studio_platform import platform_base_url; "
        "url = platform_base_url(); assert url == (sys.argv[1] or settings.STUDIO_PLATFORM_BASE_URL); "
        "assert url.startswith('https://') and url.endswith('/v1')", expected or ""],
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
        {"id": "nv-1", "name": "文本", "task_types": [1, 7], "concurrency": 5, "tool_calls": True, "json_output": True, "strict_output": True, "text_api": "responses"},
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
    assert (await client.get(path)).json()["data"] == {"connected": False, "key_management_url": "https://platform.example/#/platform/keys"}
    result = await client.put(path, json={"api_key": "nv_original"})
    assert result.json()["data"] == {"connected": True, "synced": 2}
    assert result.headers["cache-control"] == "no-store"
    assert str(calls[-1].url) == "https://platform.example/v1/models"
    assert calls[-1].headers["Authorization"] == "Bearer nv_original"
    assert "x-team-id" not in calls[-1].headers
    rows = await resolve_scope_configs(7, team_id=87)
    model = next(row for row in rows if row.scope == studio_platform.SYNC_SCOPE)
    assert model.name == "文本"
    assert model.model == "nv-1"
    assert model.concurrency == 5
    assert model.api_key == "nv_original"
    assert model.pricing == {"type": "text", "currency": "CNY", "input_price_per_1m": 2, "output_price_per_1m": 4}
    assert model.base_url == "https://platform.example/v1" and model.supports_tool_calls
    assert model.supports_strict_output is True
    assert model.text_api == "responses"
    for route in (path, "/api/config", f"/api/config/{model.id}"):
        response = await client.get(route)
        assert all(secret not in response.text for secret in ("provider-secret", "nv_original", "supplier.example"))
    assert (await client.patch(f"/api/config/{model.id}", json={"base_url": "https://other.example"})).json()["code"] == 409
    failed = await client.put(path, json={"api_key": "nv_invalid"})
    assert failed.json()["code"] == 422 and "nv_invalid" not in failed.text
    assert (await StudioPlatformConnection.get(id=1)).api_key == "nv_original"
    local_prices = {**model.pricing, "input_price_per_1m": 8}
    saved = await client.patch(f"/api/config/{model.id}", json={"pricing": local_prices, 'thinking': 'low', 'reasoning_effort': 'max'})
    assert saved.json()["code"] == 0
    models[0]["concurrency"] = 3
    models.pop()
    assert (await client.put(path, json={"api_key": "nv_replacement"})).json()["data"]["synced"] == 1
    assert (await client.post(path + "/sync")).json()["data"]["synced"] == 1
    assert calls[-1].headers["Authorization"] == "Bearer nv_replacement"
    await model.refresh_from_db()
    assert model.api_key == "nv_replacement"
    assert model.concurrency == 3
    assert model.pricing == local_prices
    assert model.thinking == 'low' and model.reasoning_effort == 'max'
    assert not await AiModelConfig.filter(scope=studio_platform.SYNC_SCOPE, model="nv-2").exists()


@pytest.mark.asyncio
async def test_sync_includes_enhancement_and_speech_without_provider_options(monkeypatch):
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_BASE_URL", "https://platform.example")
    await StudioPlatformConnection.all().delete()
    original_client = httpx.AsyncClient
    catalog = {"data": [
        {"id": "nv-801", "name": "增强", "task_types": [8],
         "pricing": {"type": "media_processing", "billing_unit": "minute", "tiers": [{"short_side_max": 1080, "fps_max": 30, "price": 1}]},
         "processing_options": {"output_resolutions": ["1080p", "4k"], "queue_id": "private-queue", "media_base_url": "https://private.example", "api_key": "secret"}},
        {"id": "nv-901", "name": "语音识别", "task_types": [9],
         "pricing": {"type": "asr", "price_per_minute": 0.02}},
    ]}
    monkeypatch.setattr(studio_platform.httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))))
    assert (await studio_platform.sync_platform_models("nv_local"))["synced"] == 2
    enhancement = await AiModelConfig.get(scope=studio_platform.SYNC_SCOPE, model="nv-801")
    speech = await AiModelConfig.get(scope=studio_platform.SYNC_SCOPE, model="nv-901")
    assert enhancement.task_types == [8] and speech.task_types == [9]
    assert enhancement.processing_options["output_resolutions"] == ["1080p", "4k"]
    assert not {"queue_id", "media_base_url", "api_key"}.intersection(enhancement.processing_options)
    assert speech.pricing["price_per_minute"] == 0.02
    assert speech.base_url == "https://platform.example/v1" and speech.api_key == "nv_local"
    catalog["data"][0]["processing_options"]["output_resolutions"] = ["720p"]
    await studio_platform.sync_platform_models()
    await enhancement.refresh_from_db()
    assert enhancement.processing_options["output_resolutions"] == ["720p"]


@pytest.mark.asyncio
async def test_sync_deletes_disabled_models_and_unused_presets_but_keeps_custom_models(monkeypatch):
    from services.model_config_seed import DEFAULT_MODELS, ensure_model_config_seed_data
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_BASE_URL", "https://platform.example")
    monkeypatch.setattr(settings, "STUDIO_PLATFORM_API_KEY", "")
    await StudioPlatformConnection.all().delete()
    await AiModelConfig.all().delete()
    preset = await AiModelConfig.create(**DEFAULT_MODELS[0], is_active=False)
    custom = await AiModelConfig.create(name="我的未启用模型", task_type=1, model="custom", base_url="https://custom.example", api_key="", is_active=False)
    original_client = httpx.AsyncClient
    catalog = {"data": [{"id": "nv-501", "name": "模型", "task_types": [1], "is_active": False}]}
    monkeypatch.setattr(studio_platform.httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))))
    assert (await studio_platform.sync_platform_models("nv_local"))["synced"] == 0
    assert not await AiModelConfig.filter(id=preset.id).exists()
    assert await AiModelConfig.filter(id=custom.id).exists()
    assert await ensure_model_config_seed_data() == 0
    catalog["data"][0]["is_active"] = True
    assert (await studio_platform.sync_platform_models())["synced"] == 1
    catalog["data"][0]["is_active"] = False
    assert (await studio_platform.sync_platform_models())["synced"] == 0
    assert not await AiModelConfig.filter(scope=studio_platform.SYNC_SCOPE).exists()
    assert await AiModelConfig.filter(id=custom.id).exists()


@pytest.mark.asyncio
async def test_seedream_catalog_preserves_each_channels_local_tariff(monkeypatch):
    tariff = {"type": "image", "currency": "CNY", "billing_unit": "pixel_tier",
              "prices": {"low": 0.13, "high_capped": 0.23}, "discount": 0.5,
              "input_image": {"first_free": 0, "price_per_image": .05}}
    legacy = {"type": "image", "currency": "CNY", "prices": {"2K": .6}}
    pro = {**tariff, "prices": {"single_low": .3, "single_high": .6, "layer_low": .15, "layer_high": .3}}
    entries = [{"id": f"nv-{i}", "name": "Seedream", "task_types": [2],
                "image_model_type": kind, "pricing": price}
               for i, (kind, price) in enumerate([("seedream_5_5", tariff), ("seedream_5_pro", legacy),
                                                   ("seedream_5_pro", pro)], 1)]
    client = httpx.AsyncClient
    monkeypatch.setattr(studio_platform.httpx, "AsyncClient", lambda **kw: client(
        **kw, transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"data": entries}))))
    await studio_platform.sync_platform_models("nv_test")
    rows = await AiModelConfig.filter(scope=studio_platform.SYNC_SCOPE).order_by("model")
    assert [row.pricing for row in rows] == [tariff, legacy, pro]
    entries[1]["pricing"] = pro
    assert await studio_platform.platform_image_tariff(rows[1].id) == pro
    await studio_platform.sync_platform_models()
    await rows[1].refresh_from_db()
    assert rows[1].pricing == legacy


@pytest.mark.asyncio
@pytest.mark.parametrize('locally_disabled', [False, True])
async def test_unknown_catalog_types_skip_one_channel_and_preserve_local_prices(monkeypatch, locally_disabled):
    entries = [{"id":"nv-31", "name":"Image", "task_types":[2], "image_model_type":"seedream_5_5"},
               {"id":"nv-32", "name":"Video", "task_types":[4], "video_model_type":"future_video"}]
    client = httpx.AsyncClient
    monkeypatch.setattr(studio_platform.httpx, "AsyncClient", lambda **kw: client(**kw,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data":entries}))))
    result = await studio_platform.sync_platform_models("nv_test")
    assert result["synced"] == 1 and result["unsupported"] == {"nv-32":"future_video"}
    row = await AiModelConfig.get(model="nv-31")
    if locally_disabled:
        from controllers.config import ai_model_config_controller
        await ai_model_config_controller.deactivate(row.id)
    await AiModelConfig.filter(id=row.id).update(pricing={"type":"image","prices":{"low":.4}})
    entries[0]["image_model_type"] = "future_image"
    result = await studio_platform.sync_platform_models()
    assert result["synced"] == 0
    await row.refresh_from_db()
    assert not row.is_active and row.pricing["prices"]["low"] == .4
    entries[0]["image_model_type"] = "seedream_5_5"
    await studio_platform.sync_platform_models()
    await row.refresh_from_db()
    assert row.is_active is (not locally_disabled) and row.pricing["prices"]["low"] == .4


@pytest.mark.asyncio
async def test_refresh_public_h3_channel_uses_advertised_resolution_prices(monkeypatch):
    from fastapi import HTTPException
    from controllers.config import ai_model_config_controller
    from services.video.capabilities import capabilities_for_config, validate_selection

    tariff = {'type': 'video', 'currency': 'CNY', 'billing_unit': 'second', 'prices': {'480p': .08, '768p': .10},
              'video_reference_prices': {'480p': 0, '768p': 0}, 'discount': .6,
              'input_image': {'first_free': 9, 'price_per_image': 0}}
    entry = {'id': 'nv-14', 'name': '优惠渠道', 'task_types': [4], 'video_model_type': 'minimax_h3', 'pricing': tariff}
    client = httpx.AsyncClient
    monkeypatch.setattr(studio_platform.httpx, 'AsyncClient', lambda **kw: client(**kw,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'data': [entry]}))))
    await studio_platform.sync_platform_models('nv_test')
    row = await AiModelConfig.get(model='nv-14')
    assert row.pricing == tariff
    await AiModelConfig.filter(id=row.id).update(pricing={**tariff, 'discount': .8,
        'prices': {'768P': .05, '2K': 0}, 'video_reference_prices': {'768P': .05, '2K': 0}})
    await studio_platform.sync_platform_models()
    await row.refresh_from_db()
    assert row.pricing == {**tariff, 'discount': .8}
    capabilities = capabilities_for_config(row)
    assert capabilities.resolutions == ('480p', '768p') and capabilities.default_resolution == '768p'
    assert (await ai_model_config_controller.list_active_video_models())[0]['capabilities'] == capabilities.public_dict()
    ai_model_config_controller._validate_pricing({'pricing': row.pricing}, row)
    options = dict(generation_mode='reference', duration=6, aspect_ratio='16:9', generate_audio=None, output_format=None)
    for tier in ('480p', '768p'):
        assert validate_selection(capabilities, resolution=tier.upper(), **options).resolution == tier
    with pytest.raises(HTTPException):
        validate_selection(capabilities, resolution='2K', **options)
    with pytest.raises(HTTPException):
        ai_model_config_controller._validate_pricing({'pricing': {**row.pricing, 'prices': {'2K': 1}}}, row)

    from services.video import get_generator
    from unittest.mock import AsyncMock
    generator = get_generator(row)
    send = AsyncMock(return_value={'id': 'test-task'})
    monkeypatch.setattr(generator, '_request', send)
    await generator.submit('测试镜头', resolution='480P', duration=6)
    assert send.await_args.kwargs['payload']['resolution'] == '480p'
    with pytest.raises(HTTPException):
        await generator.submit('测试镜头', resolution='2K', duration=6)
    assert send.await_count == 1
