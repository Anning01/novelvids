from unittest.mock import AsyncMock

import pytest

from auth.models import Team
from config import settings
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from test.test_auth.test_team_scoping import _auth, _create_member, _login

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason="AUTH_ENABLED=true permission suite")


@pytest.mark.asyncio
async def test_tail_extraction_reuses_editor_and_project_scope_checks(client, monkeypatch):
    team = await Team.create(name="tail-team")
    other = await Team.create(name="other-tail-team")
    owner, _ = await _create_member("tail-owner", team)
    viewer, _ = await _create_member("tail-viewer", team, role="viewer")
    outsider, _ = await _create_member("tail-outsider", other)
    novel = await Novel.create(name="Private tail", team_id=team.id, created_by=owner.id)
    chapter = await Chapter.create(novel=novel, number=1, name="One", content="Private")
    scene = await Scene.create(chapter=chapter, sequence=1)
    video = await Video.create(scene=scene, status=3, url="/media/source.mp4", model_type=1)
    extract = AsyncMock(return_value="/media/tail.png")
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", extract)
    path = f"/api/video/{video.id}/last-frame"
    assert (await client.post(path)).json()["code"] == 401
    assert (await client.post(path, headers=_auth(await _login(client, viewer.username)))).json()["code"] == 403
    assert (await client.post(path, headers=_auth(await _login(client, outsider.username)))).json()["code"] == 404
    extract.assert_not_awaited()
    assert (await client.post(path, headers=_auth(await _login(client, owner.username)))).json()["code"] == 0
    extract.assert_awaited_once_with(video.url, video.id, team_id=team.id)
