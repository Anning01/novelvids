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
        assert {v['id'] for v in public.json()['data']} == {f"nv-{config.id}"}
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
