import pytest
from auth.models import Team, TeamMember, User
from models.novel import Novel
from config import settings
from test.test_auth import issue_test_session

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated routes")


async def test_transfer_uses_browser_team_and_creator_role(client):
    mine = await Team.create(name="创作者")
    other = await Team.create(name="其他团队")
    author = await User.create(username="migration_author", password_hash="unused")
    await TeamMember.create(user=author, team=mine, role="creator")
    viewer = await User.create(username="migration_viewer", password_hash="unused")
    await TeamMember.create(user=viewer, team=mine, role="viewer")
    work = await Novel.create(name="只导出本团队作品", team_id=mine.id)
    foreign = await Novel.create(name="其他项目", team_id=other.id)
    async def headers(user):
        return {"Authorization":"Bearer "+await issue_test_session(user.username), "X-Team-Id":str(mine.id)}
    base = "/api/novel"
    assert (await client.get(f"{base}/{work.id}/transfer",headers=await headers(author))).json()["code"] == 0
    assert (await client.get(f"{base}/{foreign.id}/transfer",headers=await headers(author))).json()["code"] == 404
    assert (await client.get(f"{base}/{work.id}/transfer",headers=await headers(viewer))).json()["code"] == 403
    r = await client.post(base+"/import-project",headers=await headers(viewer),files={"file":("bad.zip",b"invalid")})
    assert r.json()["code"] == 403
