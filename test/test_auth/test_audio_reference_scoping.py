"""音色库按项目团队隔离，并兼容项目创建人的历史无团队音色。"""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock

from auth.models import Team, User
from auth.security import hash_password
from config import settings
from models.audio_reference import AudioReference
from models.novel import Novel
from services.oss.base import OSSProvider


pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED,
    reason="AUTH_ENABLED=false 时团队隔离不生效",
)


async def _login(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "password123"},
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]["token"]


def _headers(token: str, team_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Team-Id": str(team_id),
    }


async def _voice(
    nickname: str,
    asset_id: str,
    *,
    source: str = "upload",
    team_id: int | None = None,
    created_by: int | None = None,
) -> AudioReference:
    return await AudioReference.create(
        nickname=nickname,
        gender="男",
        audio_url=f"https://cdn.example.com/{asset_id}.mp3",
        avatar_url="",
        asset_id=asset_id,
        source=source,
        duration=5,
        team_id=team_id,
        created_by=created_by,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_超级管理员在项目内只看到可用音色(client: AsyncClient):
    boss = await User.create(
        username="voice_boss",
        nickname="voice_boss",
        password_hash=hash_password("password123"),
        is_super_admin=True,
    )
    team = await Team.create(name="音色团队")
    other_team = await Team.create(name="其他音色团队")
    novel = await Novel.create(
        name="音色作用域项目",
        author="作者",
        team_id=team.id,
        created_by=boss.id,
    )
    await _voice("系统音色", "system-voice", source="system")
    await _voice("本团队音色", "team-voice", team_id=team.id, created_by=boss.id)
    await _voice("历史音色", "legacy-voice", created_by=boss.id)
    await _voice("其他团队音色", "other-team-voice", team_id=other_team.id)
    await _voice("其他人的历史音色", "other-user-legacy", created_by=boss.id + 1)

    token = await _login(client, boss.username)
    response = await client.get(
        "/api/media-library/audio-references",
        params={"novel_id": novel.id, "page_size": 100},
        headers=_headers(token, team.id),
    )

    assert response.json()["code"] == 0, response.text
    names = {item["nickname"] for item in response.json()["data"]["items"]}
    assert names == {"系统音色", "本团队音色", "历史音色"}


@pytest.mark.asyncio
async def test_项目上传策略使用项目团队而不是超级管理员空团队(
    client: AsyncClient,
    monkeypatch,
):
    boss = await User.create(
        username="policy_boss",
        nickname="policy_boss",
        password_hash=hash_password("password123"),
        is_super_admin=True,
    )
    team = await Team.create(name="上传策略团队")
    novel = await Novel.create(
        name="上传策略项目",
        author="作者",
        team_id=team.id,
        created_by=boss.id,
    )

    class FakeProvider(OSSProvider):
        name = "fake"
        enabled = True

        def sign_form_upload(self, key, content_type, max_size):
            return {"url": "https://fake-oss/upload", "fields": {"key": key}}

        def public_url(self, key):
            return f"https://fake-cdn/{key}"

    monkeypatch.setattr("api.file.oss", FakeProvider())
    token = await _login(client, boss.username)
    response = await client.get(
        "/api/file/upload-policy",
        params={
            "filename": "角色声音.mp3",
            "content_type": "audio/mpeg",
            "novel_id": novel.id,
        },
        headers=_headers(token, team.id),
    )

    assert response.json()["code"] == 0, response.text
    assert response.json()["data"]["key"].startswith(f"uploads/{team.id}/")


@pytest.mark.asyncio
async def test_裁剪音色使用项目作用域并创建副本(
    client: AsyncClient,
    monkeypatch,
):
    boss = await User.create(
        username="trim_voice_boss",
        nickname="trim_voice_boss",
        password_hash=hash_password("password123"),
        is_super_admin=True,
    )
    team = await Team.create(name="裁剪音色团队")
    novel = await Novel.create(
        name="裁剪音色项目",
        author="作者",
        team_id=team.id,
        created_by=boss.id,
    )
    source = await _voice(
        "长音色",
        "trim-source",
        team_id=team.id,
        created_by=boss.id,
    )
    clipped = await _voice(
        "长音色 · 裁剪",
        "trim-result",
        team_id=team.id,
        created_by=boss.id,
    )
    trim = AsyncMock(return_value=clipped)
    monkeypatch.setattr("api.media_library.trim_audio_reference", trim)

    token = await _login(client, boss.username)
    response = await client.post(
        f"/api/media-library/audio-references/{source.id}/trim",
        json={"start": 1.5, "end": 4.5, "novel_id": novel.id},
        headers=_headers(token, team.id),
    )

    assert response.json()["code"] == 0, response.text
    assert response.json()["data"]["id"] == clipped.id
    trim.assert_awaited_once_with(
        source,
        start=1.5,
        end=4.5,
        team_id=team.id,
        created_by=boss.id,
    )
