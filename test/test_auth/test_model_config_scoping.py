"""模型配置分层测试：官方/团队 scope、Key 剥离、所有权、来源模式、运行时解析。

仅在 AUTH_ENABLED=true 时运行。
"""

import pytest
from httpx import AsyncClient

from test.test_auth import issue_test_session
from auth.models import Team, TeamMember, User
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
        is_super_admin=super_admin,
    )


async def _login(client: AsyncClient, username: str) -> str:
    return await issue_test_session(username)


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
async def test_enabling_team_model_makes_it_available_to_text_creation(client, config_world):
    team = config_world['team_a']
    other_team = config_world['team_b']
    headers = _auth(config_world['tokens']['admin_a'])
    created = (await client.post('/api/config', headers=headers, json={
        **TEXT_CONFIG, 'name': 'team-creation-model', 'task_type': 7, 'task_types': [7],
        'supports_strict_output': True,
    })).json()
    assert created['code'] == 0, created
    config_id = created['data']['id']
    assert (await client.get('/api/skills/models', headers=headers)).json()['data'] == []
    enabled = (await client.post(f'/api/config/{config_id}/activate', headers=headers)).json()
    assert enabled['code'] == 0, enabled
    await team.refresh_from_db()
    await other_team.refresh_from_db()
    assert team.model_config_source == 'custom'
    assert other_team.model_config_source == 'official'
    models = (await client.get('/api/skills/models', headers=headers)).json()['data']
    assert [model['id'] for model in models] == [config_id]
    from services.creation_agent.skill_execution import require_agent
    selected, _ = await require_agent(team.id, config_id, strict_output=True)
    assert selected.id == config_id
    await client.put('/api/config/team/model-source', headers=headers, json={'source': 'official'})
    assert (await client.get('/api/skills/models', headers=headers)).json()['data'] == []


@pytest.mark.asyncio
async def test_enabling_official_model_keeps_team_source_unchanged(client, config_world):
    model = await AiModelConfig.create(name='official-activation', task_type=7, task_types=[7],
        model='test', base_url='https://example.invalid', api_key='test-only')
    reply = await client.post(f'/api/config/{model.id}/activate', headers=_auth(config_world['tokens']['boss']))
    assert reply.json()['code'] == 0
    assert await Team.filter(model_config_source='custom').count() == 0


@pytest.mark.asyncio
async def test_team_activation_preserves_capability_filter_and_official_fallback(client, config_world):
    headers = _auth(config_world['tokens']['admin_a'])
    official = await AiModelConfig.create(name='official-strict', task_type=7, task_types=[7],
        model='test', base_url='https://example.invalid', api_key='test-only',
        is_active=True, supports_strict_output=True)
    team_model = await AiModelConfig.create(name='team-without-strict', task_type=7, task_types=[7],
        model='test', base_url='https://example.invalid', api_key='test-only',
        team_id=config_world['team_a'].id, scope='team', supports_strict_output=False)
    await client.post(f'/api/config/{team_model.id}/activate', headers=headers)
    await team_model.refresh_from_db()
    assert team_model.supports_strict_output is False
    available = (await client.get('/api/skills/models', headers=headers)).json()['data']
    assert [model['id'] for model in available] == [official.id]


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['POST', 'PATCH', 'PUT'])
async def test_enabling_team_model_through_save_selects_custom_source(client, config_world, method):
    headers = _auth(config_world['tokens']['admin_a'])
    body = {**TEXT_CONFIG, 'name': f'enabled-{method}', 'task_type': 7, 'task_types': [7],
            'is_active': True, 'supports_strict_output': True}
    path = '/api/config'
    if method != 'POST':
        model = await AiModelConfig.create(name=body['name'], task_type=7, task_types=[7],
            model='test-model', base_url='https://example.invalid', api_key='test-only',
            team_id=config_world['team_a'].id, scope='team')
        path += f'/{model.id}'
    response = await client.request(method, path, headers=headers, json=body)
    assert response.json()['code'] == 0, response.json()
    await config_world['team_a'].refresh_from_db()
    assert config_world['team_a'].model_config_source == 'custom'


@pytest.mark.asyncio
async def test_source_failure_rolls_back_model_activation(client, config_world, monkeypatch):
    from unittest.mock import AsyncMock
    model = await AiModelConfig.create(name='atomic-activation', task_type=7, task_types=[7],
        model='test-model', base_url='https://example.invalid', api_key='test-only',
        team_id=config_world['team_a'].id, scope='team')
    monkeypatch.setattr(ai_model_config_controller, 'set_model_config_source', AsyncMock(side_effect=RuntimeError('test failure')))
    with pytest.raises(RuntimeError, match='test failure'):
        await ai_model_config_controller.activate(model.id)
    await model.refresh_from_db()
    assert not model.is_active
    await config_world['team_a'].refresh_from_db()
    assert config_world['team_a'].model_config_source == 'official'


@pytest.mark.asyncio
async def test_team_admin_sees_only_own_team_configs(client, config_world):
    """平台级配置对团队不可见：团队管理员只看到本团队自定义配置。"""
    # 官方配置（超管创建）
    await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "official-secret"}, headers=_auth(config_world["tokens"]["boss"])
    )
    # 本团队配置
    await client.post(
        "/api/config", json={**TEXT_CONFIG, "name": "team-a-secret"}, headers=_auth(config_world["tokens"]["admin_a"])
    )

    response = await client.get("/api/config", headers=_auth(config_world["tokens"]["admin_a"]))
    items = {item["name"]: item for item in response.json()["data"]["items"]}
    assert set(items) == {"team-a-secret"}
    # 本团队 Key 可见
    assert items["team-a-secret"]["api_key"] == "sk-secret-key"
    assert items["team-a-secret"]["scope"] == "team"

    # 超管可见全量（官方 + 各团队）
    boss_list = await client.get("/api/config", headers=_auth(config_world["tokens"]["boss"]))
    boss_names = {item["name"] for item in boss_list.json()["data"]["items"]}
    assert boss_names == {"official-secret", "team-a-secret"}


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

    # 官方配置详情：团队管理员不可见（平台级配置只有超管可查看）
    detail = await client.get(f"/api/config/{config_id}", headers=_auth(config_world["tokens"]["admin_a"]))
    assert detail.json()["code"] == 404
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
    """运行时解析：来源模式 official 时仅用官方；custom 时团队配置优先，官方兜底。"""
    team = await Team.create(name="解析队")  # 默认 model_config_source="official"
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

    # 团队启用配置，但来源模式仍为 official：应继续使用官方配置
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
    assert resolved.id == official.id

    # 切换为 custom 后，团队配置优先命中
    team.model_config_source = "custom"
    await team.save(update_fields=["model_config_source", "updated_at"])
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


@pytest.mark.asyncio
async def test_reference_upload_rejects_other_teams_model_config(client):
    from unittest.mock import AsyncMock, patch
    team_a = await Team.create(name="reference-own")
    team_b = await Team.create(name="reference-foreign")
    user = await _create_user("reference-user")
    await TeamMember.create(team=team_a, user=user, role="creator")
    config = await AiModelConfig.create(name="private-image", task_type=AiTaskTypeEnum.reference_image.value,
        team_id=team_b.id, scope="team", model="test", api_key="test", base_url="https://example.invalid",
        image_model_type="gemini", is_active=True)
    with patch("api.video.save_reference_upload", new_callable=AsyncMock) as save:
        result = await client.post("/api/video/reference/upload",
            headers=_auth(await issue_test_session(user.username)),
            data={"model_config_id": config.id}, files={"file": ("image.png", b"not-an-image", "image/png")})
        assert result.json()["code"] == 400
        save.assert_not_awaited()
