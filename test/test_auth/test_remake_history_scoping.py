"""历史重制目录的团队隔离和超管访问。"""

import pytest
from httpx import AsyncClient

from auth.models import Team, TeamMember, User
from auth.security import hash_password
from config import settings
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from utils.enums import TaskStatusEnum, TeamRoleEnum, VideoModelTypeEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED,
    reason="AUTH_ENABLED=false 时团队隔离不生效",
)


async def _available_project(name: str, team_id: int) -> Novel:
    novel = await Novel.create(name=name, author="作者", team_id=team_id)
    chapter = await Chapter.create(
        novel=novel,
        number=1,
        name="第1集",
        content="",
    )
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="镜头", duration=5)
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/ready.mp4",
        metadata={"size_bytes": 1024},
    )
    scene.metadata = {"workbench": {"activeVideoId": video.id}}
    await scene.save(update_fields=["metadata", "updated_at"])
    return novel


async def _login(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "password123"},
    )
    token = response.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_history_catalog_is_team_scoped_and_super_admin_can_read_all(client):
    team_a = await Team.create(name="历史团队A")
    team_b = await Team.create(name="历史团队B")
    member = await User.create(
        username="history_member",
        nickname="history_member",
        password_hash=hash_password("password123"),
    )
    await TeamMember.create(
        team=team_a,
        user=member,
        role=TeamRoleEnum.creator.value,
    )
    boss = await User.create(
        username="history_boss",
        nickname="history_boss",
        password_hash=hash_password("password123"),
        is_super_admin=True,
    )
    project_a = await _available_project("历史A项目", team_a.id)
    project_b = await _available_project("历史B项目", team_b.id)

    member_headers = await _login(client, member.username)
    member_catalog = await client.get(
        "/api/remake/history/projects",
        headers=member_headers,
    )
    assert [item["id"] for item in member_catalog.json()["data"]["items"]] == [
        project_a.id
    ]

    forbidden = await client.get(
        f"/api/remake/history/projects/{project_b.id}/episodes",
        headers=member_headers,
    )
    assert forbidden.json()["code"] == 403
    assert forbidden.json()["data"]["error_code"] == "REMAKE_HISTORY_PROJECT_FORBIDDEN"

    boss_headers = await _login(client, boss.username)
    boss_catalog = await client.get(
        "/api/remake/history/projects",
        headers=boss_headers,
    )
    assert {item["id"] for item in boss_catalog.json()["data"]["items"]} == {
        project_a.id,
        project_b.id,
    }
