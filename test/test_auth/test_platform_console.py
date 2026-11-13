import subprocess
import sys
import os
import pytest

from auth.models import PlatformApiKey, Team, TeamMember, User
from config import settings
from models.config import AiModelConfig
from test.test_auth import issue_test_session


def test_roles_register_different_public_surfaces():
    code = """
from main import app
paths=app.openapi()['paths']
public = next(r.app for r in app.routes if getattr(r, 'path', None) == '/v1')
assert '/models' in public.openapi()['paths'] and '/api/platform/catalog' in paths
assert '/api/chapter/{chapter_id}/screenplay' not in paths
assert '/api/file/upload-policy' not in paths and '/api/novel/import-project' not in paths
assert '/api/novel' not in paths and '/api/workbench/bootstrap' not in paths
"""
    subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ, "AUTH_ENABLED":"true", "NOVELVIDS_ROLE":"platform","API_DOCS_ENABLED":"true"})


@pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated accounts")
@pytest.mark.asyncio
async def test_personal_keys_are_one_time_revocable_and_do_not_cross_teams():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from api.platform import console_router, developer_router
    from services.schema_compat import ensure_team_schema
    app = FastAPI()
    app.include_router(console_router,prefix="/api")
    app.include_router(developer_router,prefix="/v1")
    user = await User.create(username="console-user", password_hash="!")
    foreign = await User.create(username="console-foreign", password_hash="!")
    team = await Team.create(name="我的控制台")
    membership = await TeamMember.create(team=team,user=user,role="creator")
    await TeamMember.create(team=team,user=foreign,role="creator")
    async def session(actor):
        return {"Authorization":"Bearer "+await issue_test_session(actor.username),"X-Team-Id":str(team.id)}
    config = await AiModelConfig.create(name="公共模型", model="provider-internal",task_type=7,
        base_url="https://example.invalid",api_key="test-secret-value",is_active=True)
    await AiModelConfig.create(name="团队私有", scope="team",team_id=team.id,model="hidden",task_type=7,
        base_url="https://example.invalid",api_key="test",is_active=True)
    for task_type in (8, 9):
        await AiModelConfig.create(name=f"工作台模型 {task_type}", model="studio-only", task_type=task_type,
            base_url="https://example.invalid", api_key="test", is_active=True)
    mixed = await AiModelConfig.create(name="混合能力模型", model="mixed", task_type=7, task_types=[7, 9],
        base_url="https://example.invalid", api_key="test", is_active=True)
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as http:
        headers = await session(user)
        minted = await http.post("/api/platform/keys",headers=headers,json={"name":"本地工作台"})
        assert minted.status_code == 200 and minted.headers['cache-control']=='no-store'
        key = minted.json()["data"]
        await ensure_team_schema()
        await ensure_team_schema()
        row = await PlatformApiKey.get(id=key["id"])
        assert row.token_hash != key["key"] and key["key"] not in (await http.get("/api/platform/keys",headers=headers)).text
        developer = {"Authorization":"Bearer "+key["key"]}
        public = await http.get("/v1/models",headers=developer)
        assert public.status_code == 200
        expected = {f"nv-{config.id}": ["text"], f"nv-{mixed.id}": ["text"]}
        assert {v["id"]: v["kinds"] for v in public.json()["data"]} == expected
        catalog = await http.get("/api/platform/catalog")
        assert {v["id"]: v["kinds"] for v in catalog.json()["data"]} == expected
        assert "test-secret-value" not in public.text and "example.invalid" not in public.text
        assert (await http.get("/v1/models",headers=headers)).status_code == 401
        assert (await http.get("/v1/models",params={"token":key["key"]})).status_code == 401
        assert (await http.delete(f"/api/platform/keys/{row.id}",headers=await session(foreign))).status_code == 404
        membership.status = 0
        await membership.save()
        assert (await http.get("/v1/models",headers=developer)).status_code == 403
        membership.status = 1
        await membership.save()
        assert (await http.delete(f"/api/platform/keys/{row.id}",headers=headers)).status_code == 200
        assert (await http.get("/v1/models",headers=developer)).status_code == 401


@pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated accounts")
@pytest.mark.asyncio
async def test_console_usage_uses_platform_billing_and_member_scope():
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI
    from models.usage_record import ModelUsageRecord
    from api.platform import console_router
    app = FastAPI()
    app.include_router(console_router, prefix="/api")
    team = await Team.create(name="统计团队")
    author = await User.create(username="usage-author",password_hash="!")
    await TeamMember.create(team=team,user=author,role="creator")
    for user_id, source in [(author.id,"balance"),(author.id,"team_key"),(author.id+100,"balance")]:
        await ModelUsageRecord.create(novel_id=1,task_type=7,billing_type="text",model="text",cost=5,
                                      team_id=team.id,user_id=user_id,cost_source=source)
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        data = (await client.get("/api/platform/usage",headers={"Authorization":"Bearer "+await issue_test_session(author.username),
                 "X-Team-Id":str(team.id)})).json()["data"]
    assert data["total_cost"] == 5 and data["total_records"] == 1 and data["daily_trend"][0]["cost"] == 5


@pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated accounts")
async def test_console_usage_applies_one_reporting_window_to_all_totals():
    from datetime import datetime, time, timedelta, timezone

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from api.platform import console_router
    from models.usage_record import ModelUsageRecord

    app = FastAPI()
    app.include_router(console_router, prefix="/api")
    team = await Team.create(name="用量日期团队")
    author = await User.create(username="usage-window", password_hash="!")
    await TeamMember.create(team=team, user=author, role="creator")
    today = datetime.now(settings.tz).date()
    first = today - timedelta(days=6)
    midnight = datetime.combine(first, time.min, settings.tz).astimezone(timezone.utc)
    for name, created_at, cost in [("旧模型", midnight - timedelta(microseconds=1), 5),
                                   ("当前模型", midnight, 2), ("当前模型", midnight + timedelta(hours=1), 3)]:
        record = await ModelUsageRecord.create(novel_id=0, task_type=7, billing_type="text", model=name,
            cost=cost, team_id=team.id, user_id=author.id, cost_source="balance")
        await ModelUsageRecord.filter(id=record.id).update(created_at=created_at)
    headers = {"Authorization": "Bearer " + await issue_test_session(author.username), "X-Team-Id": str(team.id)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        usage = "/api/platform/usage"
        recent = (await client.get(usage, params={"days": 7})).json()["data"]
        month = (await client.get(usage, params={"days": 30})).json()["data"]
        assert (await client.get(usage, params={"days": 0})).status_code == 422

    assert recent["total_cost"] == 5 and recent["total_records"] == 2
    assert recent["by_model"] == [{"model": "当前模型", "cost": 5, "record_count": 2}]
    assert recent["daily_trend"] == [{"date": (first + timedelta(days=i)).isoformat(), "cost": 5 if i == 0 else 0}
                                     for i in range(7)]
    assert month["total_cost"] == 10 and month["total_records"] == 3
    assert len(month["daily_trend"]) == 30


@pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated accounts")
@pytest.mark.parametrize("role", ["admin", "creator", "viewer"])
async def test_platform_provider_settings_are_administrator_only(role):
    from fastapi import FastAPI
    from httpx import ASGITransport,AsyncClient
    from api.platform import console_router
    app=FastAPI()
    app.include_router(console_router,prefix="/api")
    team=await Team.create(name="平台配置权限")
    regular=await User.create(username="platform-config-user",password_hash="!")
    await TeamMember.create(team=team,user=regular,role=role)
    config = await AiModelConfig.create(name="平台受限模型", model="upstream", task_type=7,
        base_url="https://example.invalid", api_key="test-only-secret")
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        headers = {"Authorization":"Bearer "+await issue_test_session(regular.username), "X-Team-Id":str(team.id)}
        payload = {"name":"普通成员配置","model":"upstream","task_type":7,"base_url":"https://example.invalid","api_key":"test"}
        for method, path in [("GET", ""), ("POST", ""), ("GET", f"/{config.id}"),
                             ("PUT", f"/{config.id}"), ("PATCH", f"/{config.id}"),
                             ("POST", f"/{config.id}/activate"), ("POST", f"/{config.id}/deactivate"),
                             ("DELETE", f"/{config.id}")]:
            r = await client.request(method, "/api/config" + path, headers=headers,
                **({"json":payload} if method in {"POST","PUT","PATCH"} else {}))
            assert r.status_code == 403, (role, method, path)
            assert "test-only-secret" not in r.text
        assert (await client.get("/api/config")).status_code==401
    assert await AiModelConfig.filter(id=config.id, name="平台受限模型").exists()


@pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated accounts")
async def test_super_admin_keeps_platform_model_scope_when_a_team_is_selected(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from api.platform import console_router

    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "platform")
    app = FastAPI()
    app.include_router(console_router, prefix="/api")
    boss = await User.create(username="platform-model-super", password_hash="!", is_super_admin=True)
    team = await Team.create(name="超管当前团队")
    await TeamMember.create(team=team, user=boss, role="viewer")
    headers = {"Authorization":"Bearer " + await issue_test_session(boss.username), "X-Team-Id":str(team.id)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        result = await client.post("/api/config", json={"name":"全局平台模型", "task_type":7, "model":"upstream",
            "base_url":"https://example.invalid", "api_key":"test"})
        assert result.status_code == 200
        config = result.json()["data"]
        assert config["scope"] == "official" and config["team_id"] is None
        changed = await client.patch(f"/api/config/{config['id']}", json={"name":"更新平台模型"})
        assert changed.status_code == 200 and changed.json()["data"]["name"] == "更新平台模型"
