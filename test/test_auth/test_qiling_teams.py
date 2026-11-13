import pytest

from test.test_auth import issue_test_session
from auth import qiling
from auth.account_consolidation import consolidate_platform_account
from auth.models import QilingIdentity, Team, TeamMember, User, UserSession
from config import settings
from models.novel import Novel
from services.schema_compat import ensure_team_schema

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires auth")]


async def login(client, user):
    return {"Authorization": "Bearer " + await issue_test_session(user.username)}


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "platform")
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "qiling")
    monkeypatch.setattr(settings, "QILING_API_BASE_URL", "https://qiling.example.test")
    monkeypatch.setattr(settings, "QILING_SIGNUP_ENABLED", True)
    from test.test_services.test_legal_documents import configure_legal
    configure_legal(monkeypatch)
    state = {"status": "pending", "subject": "qiling-person-1"}

    async def request(method, path, **kwargs):
        if path.endswith("/session"):
            assert method == "POST"
            return {"state": "upstream-only", "auth_url": "https://wx.example.test/authorize", "expires_in": 300}
        if path.endswith("/status/upstream-only"):
            return {"status": state["status"], "access_token": "upstream-only-token"}
        assert path == "/api/v1/auth/me"
        assert kwargs["headers"]["Authorization"] == "Bearer upstream-only-token"
        return {"sub": state["subject"], "name": "扫码用户", "role": "platform_admin"}

    monkeypatch.setattr(qiling, "_request", request)
    return state


async def test_qiling_signup_only_after_confirmation_and_local_attempt_is_one_time(client, upstream):
    start = (await client.post("/api/auth/qiling/start")).json()["data"]
    assert "upstream_state" not in start
    url = "/api/auth/qiling/poll"
    body = {"attempt": start["attempt"]}
    assert (await client.post(url, json=body)).json()["data"] == {"status": "pending"}
    assert not await QilingIdentity.all().exists()

    upstream["status"] = "completed"
    result = (await client.post(url, json=body)).json()["data"]
    assert result["status"] == "completed"
    assert result["session"]["user"]["is_super_admin"] is False
    assert "upstream-only-token" not in str(result)
    token = {"Authorization": "Bearer " + result["session"]["token"]}
    me = (await client.get("/api/auth/me", headers=token)).json()["data"]
    assert me["qiling_bound"] and me["owns_team"]
    membership, = me["memberships"]
    owned = await Team.get(owner_user_id=result["session"]["user"]["id"])
    assert membership["team_id"] == owned.id and membership["role"] == "admin"
    assert membership["is_owner"] is True
    assert owned.name == "扫码用户的团队"
    assert (await client.post(url, json=body)).json()["data"] == {"status": "expired"}


async def test_registration_can_be_disabled_and_binding_keeps_existing_account(client, upstream, monkeypatch):
    monkeypatch.setattr(settings, "QILING_SIGNUP_ENABLED", False)
    upstream["status"] = "completed"
    start = (await client.post("/api/auth/qiling/start")).json()["data"]
    assert (await client.post("/api/auth/qiling/poll", json={"attempt": start["attempt"]})).json()["code"] == 403

    existing = await User.create(username="existing")
    other = await User.create(username="other")
    headers, other_headers = await login(client, existing), await login(client, other)
    start = (await client.post("/api/auth/qiling/bind/start", headers=headers)).json()["data"]
    body = {"attempt": start["attempt"]}
    assert (await client.post("/api/auth/qiling/bind/poll", headers=other_headers, json=body)).json()["data"]["status"] == "expired"
    assert (await client.post("/api/auth/qiling/poll", json=body)).json()["data"]["status"] == "expired"
    assert (await client.post("/api/auth/qiling/bind/poll", headers=headers, json=body)).json()["data"]["status"] == "bound"

    start = (await client.post("/api/auth/qiling/start")).json()["data"]
    result = (await client.post("/api/auth/qiling/poll", json={"attempt": start["attempt"]})).json()["data"]
    assert result["session"]["user"]["id"] == existing.id
    assert not await Team.filter(owner_user_id=existing.id).exists()


async def test_disabled_linked_account_cannot_sign_in_with_qiling(client, upstream):
    user = await User.create(username="disabled-qiling", status=0)
    await QilingIdentity.create(user=user, issuer=settings.QILING_API_BASE_URL, subject=upstream["subject"])
    upstream["status"] = "completed"
    start = (await client.post("/api/auth/qiling/start")).json()["data"]
    result = (await client.post("/api/auth/qiling/poll", json={"attempt": start["attempt"]})).json()
    assert result["code"] == 403
    assert not await UserSession.filter(user_id=user.id).exists()


async def test_super_account_retains_platform_permissions_when_filtering_by_team(client):
    user = await User.create(username="operator", is_super_admin=True)
    team = await Team.create(name="Selected")
    other = await Team.create(name="Other")
    await TeamMember.create(user=user, team=team, role="viewer")
    selected = await Novel.create(name="Selected work", team_id=team.id)
    foreign = await Novel.create(name="Other work", team_id=other.id)
    headers = await login(client, user)
    platform = (await client.get("/api/novel", headers=headers)).json()["data"]["items"]
    assert {item["id"] for item in platform} == {selected.id, foreign.id}
    scoped = {**headers, "X-Team-Id": str(team.id)}
    assert [item["id"] for item in (await client.get("/api/novel", headers=scoped)).json()["data"]["items"]] == [selected.id]
    assert (await client.get(f"/api/novel/{foreign.id}", headers=scoped)).json()["code"] == 0
    assert (await client.get("/api/users", headers=scoped)).json()["code"] == 0
    assert (await client.get("/api/novel", headers={**headers, "X-Team-Id": str(other.id)})).json()["code"] == 0
    payload = {"name": "New work", "content": "Manuscript"}
    assert (await client.post("/api/novel", headers=headers, json=payload)).json()["code"] == 403
    assert (await client.post("/api/novel", headers=scoped, json={**payload, "name": "Super work"})).json()["code"] == 0
    await TeamMember.filter(team=team, user=user).update(role="creator")
    assert (await client.post("/api/novel", headers=scoped, json=payload)).json()["code"] == 0
    assert await Novel.filter(name="New work", team_id=team.id, created_by=user.id).exists()


async def test_signup_team_is_unique_and_joining_requires_an_invite(client, upstream):
    owner = await User.create(username="original")
    existing = await Team.create(name="扫码用户的团队", owner_user_id=owner.id)
    upstream["status"] = "completed"

    async def sign_in():
        start = (await client.post("/api/auth/qiling/start")).json()["data"]
        return (await client.post("/api/auth/qiling/poll", json={"attempt": start["attempt"]})).json()["data"]["session"]

    session = await sign_in()
    user_id = session["user"]["id"]
    headers = {"Authorization": "Bearer " + session["token"]}
    owned = await Team.get(owner_user_id=user_id)
    assert owned.name == "扫码用户的团队 (2)"
    assert (await sign_in())["user"]["id"] == user_id
    assert await Team.filter(owner_user_id=user_id).count() == 1
    assert (await client.post("/api/team/mine", headers=headers, json={"name": "Extra"})).json()["code"] == 404
    assert not await TeamMember.filter(user_id=user_id, team_id=existing.id).exists()
    from services.invites import create_invite

    invite = await create_invite(existing.id, "viewer")
    reply = await client.post(f"/api/team/invites/{invite.token}/join", headers=headers)
    assert reply.json()["code"] == 0
    assert await TeamMember.filter(user_id=user_id, team_id=existing.id, role="viewer").exists()
    assert await TeamMember.filter(user_id=user_id, team_id=owned.id, role="admin").exists()


async def test_early_qiling_signup_without_membership_gets_its_team_on_next_login(client, upstream):
    user = await User.create(username="qiling-early", nickname="早期注册")
    await QilingIdentity.create(user=user, issuer=settings.QILING_API_BASE_URL, subject=upstream["subject"])
    upstream["status"] = "completed"
    start = (await client.post("/api/auth/qiling/start")).json()["data"]
    result = (await client.post("/api/auth/qiling/poll", json={"attempt": start["attempt"]})).json()["data"]
    assert result["session"]["user"]["id"] == user.id
    team = await Team.get(owner_user_id=user.id)
    assert await TeamMember.filter(team=team, user=user, role="admin").exists()


async def test_consolidation_preserves_team_and_project_owner_and_revokes_old_sessions(client):
    admin = await User.create(username="admin", is_super_admin=True)
    personal = await User.create(username="anning")
    team = await Team.create(name="Creative team")
    await TeamMember.create(user=personal, team=team, role="creator")
    work = await Novel.create(name="Existing work", team_id=team.id, created_by=personal.id)
    old_admin, old_personal = await login(client, admin), await login(client, personal)
    with pytest.raises(ValueError, match="first bind"):
        await consolidate_platform_account(admin.id, personal.id)
    await QilingIdentity.create(user=personal, issuer="https://qiling.example.test", subject="anning-external")
    await consolidate_platform_account(admin.id, personal.id)
    await admin.refresh_from_db()
    await personal.refresh_from_db()
    await work.refresh_from_db()
    assert admin.status == 0 and not admin.is_super_admin
    assert personal.is_super_admin and work.created_by == personal.id and work.team_id == team.id
    assert not await UserSession.filter(user_id__in=[admin.id, personal.id]).exists()
    for headers in (old_admin, old_personal):
        assert (await client.get("/api/auth/me", headers=headers)).json()["code"] == 401


async def test_qiling_schema_is_safe_to_initialize_twice():
    await ensure_team_schema()
    await ensure_team_schema()
    assert await QilingIdentity.all().count() == 0


async def test_first_admin_can_only_be_provisioned_from_a_verified_qiling_account():
    first = await User.create(username="first-admin")
    other = await User.create(username="other-admin")
    with pytest.raises(ValueError, match="first bind"):
        await consolidate_platform_account(None, first.id)
    for user in (first, other):
        await QilingIdentity.create(user=user, issuer="https://qiling.example.test", subject=user.username)
    await consolidate_platform_account(None, first.id)
    assert await User.filter(id=first.id, is_super_admin=True).exists()
    with pytest.raises(ValueError, match="active administrator exists"):
        await consolidate_platform_account(None, other.id)


async def test_qiling_schema_keeps_legacy_rows_without_assigning_them_an_issuer(monkeypatch):
    from tortoise.backends.sqlite.client import SqliteClient

    from services.schema_compat import _ensure_qiling_issuer_columns

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite://:memory:")
    legacy = SqliteClient(file_path=":memory:", connection_name="legacy")
    try:
        await legacy.execute_script("""
            CREATE TABLE qiling_identities (subject VARCHAR(100) UNIQUE);
            CREATE TABLE qiling_login_attempts (upstream_state VARCHAR(200));
            INSERT INTO qiling_identities VALUES ('existing');
            INSERT INTO qiling_login_attempts VALUES ('old');
        """)
        await _ensure_qiling_issuer_columns(legacy)
        await _ensure_qiling_issuer_columns(legacy)
        assert await legacy.execute_query_dict("SELECT subject, issuer FROM qiling_identities") == [
            {"subject": "existing", "issuer": ""},
        ]
        assert await legacy.execute_query_dict("SELECT upstream_state, issuer FROM qiling_login_attempts") == [
            {"upstream_state": "old", "issuer": ""},
        ]
    finally:
        await legacy.close()
