"""模型配置分层测试：官方/团队 scope、Key 剥离、所有权、来源模式、运行时解析。

仅在 AUTH_ENABLED=true 时运行。
"""

import pytest
from httpx import AsyncClient

from auth.models import Team, TeamMember, User
from auth.security import hash_password
from config import settings
from controllers.config import ai_model_config_controller
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum, TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时配置分层不生效"
)

PASSWORD = "password123"

TEXT_CONFIG = {
    "task_type": AiTaskTypeEnum.extraction.value,
    "name": "unique-name",
    "base_url": "https://example.com/v1",
    "api_key": "sk-secret-key",
    "model": "test-model",
    "supports_json_output": False,
}


async def _create_user(username: str, *, super_admin: bool = False) -> User:
    return await User.create(
        username=username,
        nickname=username,
        password_hash=hash_password(PASSWORD),
        is_super_admin=super_admin,
    )


async def _login(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_world(client: AsyncClient):
    team_a = await Team.create(name="配置A队")
    team_b = await Team.create(name="配置B队")
    admin_a = await _create_user("cfg_admin_a")
    admin_b = await _create_user("cfg_admin_b")
    boss = await _create_user("cfg_boss", super_admin=True)
    await TeamMember.create(team=team_a, user=admin_a, role=TeamRoleEnum.admin.value)
    await TeamMember.create(team=team_b, user=admin_b, role=TeamRoleEnum.admin.value)
    tokens = {
        "admin_a": await _login(client, "cfg_admin_a"),
        "admin_b": await _login(client, "cfg_admin_b"),
        "boss": await _login(client, "cfg_boss"),
    }
    return {"team_a": team_a, "team_b": team_b, "tokens": tokens}


@pytest.fixture
async def config_world(client: AsyncClient):
    return await _make_world(client)


@pytest.mark.asyncio
async def test_super_admin_creates_official_config(client, config_world):
    response = await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "official-cfg"}, headers=_auth(config_world["tokens"]["boss"])
    )
    assert response.json()["code"] == 0, response.text
    instance = await AiModelConfig.get(name="official-cfg")
    assert instance.scope == "official"
    assert instance.team_id is None


@pytest.mark.asyncio
async def test_team_admin_creates_team_config(client, config_world):
    response = await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "team-a-cfg"}, headers=_auth(config_world["tokens"]["admin_a"])
    )
    assert response.json()["code"] == 0, response.text
    instance = await AiModelConfig.get(name="team-a-cfg")
    assert instance.scope == "team"
    assert instance.team_id == config_world["team_a"].id


@pytest.mark.asyncio
async def test_team_admin_list_sees_own_and_official_with_key_masked(client, config_world):
    # 官方配置（超管创建，含真实 Key）
    await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "official-secret"}, headers=_auth(config_world["tokens"]["boss"])
    )
    # 本团队配置
    await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "team-a-secret"}, headers=_auth(config_world["tokens"]["admin_a"])
    )

    response = await client.get("/api/config", headers=_auth(config_world["tokens"]["admin_a"]))
    items = {item["name"]: item for item in response.json()["data"]["items"]}
    assert set(items) == {"official-secret", "team-a-secret"}
    # 官方配置 Key 必须剥离
    assert items["official-secret"]["api_key"] is None
    assert items["official-secret"]["scope"] == "official"
    # 本团队 Key 可见
    assert items["team-a-secret"]["api_key"] == "sk-secret-key"
    assert items["team-a-secret"]["scope"] == "team"
    assert items["team-a-secret"]["team_id"] == config_world["team_a"].id


@pytest.mark.asyncio
async def test_team_admin_cannot_mutate_official_config(client, config_world):
    created = await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "official-frozen"}, headers=_auth(config_world["tokens"]["boss"])
    )
    config_id = created.json()["data"]["id"]

    for method, path, payload in (
        ("PATCH", f"/api/config/{config_id}", {"name": "hack"}),
        ("DELETE", f"/api/config/{config_id}", None),
        ("POST", f"/api/config/{config_id}/activate", None),
    ):
        response = await client.request(
            method, path, json=payload, headers=_auth(config_world["tokens"]["admin_a"])
        ) if payload is not None else await client.request(
            method, path, headers=_auth(config_world["tokens"]["admin_a"])
        )
        assert response.json()["code"] == 404, f"{method} {path}: {response.text}"

    # 官方配置详情：Key 掩码可见，但内容未被篡改
    detail = await client.get(f"/api/config/{config_id}", headers=_auth(config_world["tokens"]["admin_a"]))
    assert detail.json()["code"] == 0
    assert detail.json()["data"]["api_key"] is None
    assert (await AiModelConfig.get(id=config_id)).name == "official-frozen"


@pytest.mark.asyncio
async def test_team_admin_cannot_see_other_team_config(client, config_world):
    created = await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "team-b-private"}, headers=_auth(config_world["tokens"]["admin_b"])
    )
    config_id = created.json()["data"]["id"]

    # 列表不可见
    response = await client.get("/api/config", headers=_auth(config_world["tokens"]["admin_a"]))
    names = [item["name"] for item in response.json()["data"]["items"]]
    assert "team-b-private" not in names
    # 详情 404
    detail = await client.get(f"/api/config/{config_id}", headers=_auth(config_world["tokens"]["admin_a"]))
    assert detail.json()["code"] == 404


@pytest.mark.asyncio
async def test_model_source_mode_switch(client, config_world):
    token = config_world["tokens"]["admin_a"]
    current = await client.get("/api/config/team/model-source", headers=_auth(token))
    assert current.json()["data"]["source"] == "official"

    switched = await client.put(
        "/api/config/team/model-source", json={"source": "custom"}, headers=_auth(token)
    )
    assert switched.json()["data"]["source"] == "custom"

    persisted = await client.get("/api/config/team/model-source", headers=_auth(token))
    assert persisted.json()["data"]["source"] == "custom"

    invalid = await client.put(
        "/api/config/team/model-source", json={"source": "nonsense"}, headers=_auth(token)
    )
    assert invalid.json()["code"] == 422


@pytest.mark.asyncio
async def test_super_admin_has_no_team_model_source(client, config_world):
    response = await client.get(
        "/api/config/team/model-source", headers=_auth(config_world["tokens"]["boss"])
    )
    assert response.json()["code"] == 403


@pytest.mark.asyncio
async def test_get_active_prefers_team_config_then_official():
    """运行时解析：团队自定义启用项优先，无团队配置时回退官方。"""
    team = await Team.create(name="解析队")
    # 官方启用配置
    official = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value],
        name="官方文本",
        base_url="https://official",
        api_key="k-official",
        model="official-model",
        is_active=True,
        scope="official",
        team_id=None,
    )
    resolved = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.extraction.value, team_id=team.id
    )
    assert resolved.id == official.id

    # 团队启用配置后应优先命中
    team_config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value],
        name="团队文本",
        base_url="https://team",
        api_key="k-team",
        model="team-model",
        is_active=True,
        scope="team",
        team_id=team.id,
    )
    resolved = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.extraction.value, team_id=team.id
    )
    assert resolved.id == team_config.id

    # 停用团队配置后回退官方
    team_config.is_active = False
    await team_config.save(update_fields=["is_active", "updated_at"])
    resolved = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.extraction.value, team_id=team.id
    )
    assert resolved.id == official.id


@pytest.mark.asyncio
async def test_get_active_rejects_other_team_explicit_config():
    team_a = await Team.create(name="显式A队")
    team_b = await Team.create(name="显式B队")
    other = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value],
        name="B队专属",
        base_url="https://b",
        api_key="k",
        model="b-model",
        is_active=True,
        scope="team",
        team_id=team_b.id,
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await ai_model_config_controller.get_active(
            AiTaskTypeEnum.extraction.value,
            config_id=other.id,
            team_id=team_a.id,
        )
    assert exc.value.status_code == 400
