import pytest
from uuid import uuid4
from auth.models import Team
from config import settings
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from test.test_auth.test_team_scoping import _create_member, _login, _auth

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason='Requires AUTH_ENABLED=true role/team tests')


@pytest.mark.asyncio
async def test_sheet_history_and_writes_enforce_team_and_role(client):
    own = await Team.create(name='Sheet owners')
    other = await Team.create(name='Other team')
    owner,_ = await _create_member('sheet-owner',own)
    viewer,_ = await _create_member('sheet-reader',own,role='viewer')
    stranger,_ = await _create_member('sheet-stranger',other)
    novel = await Novel.create(name='Private sheet',team_id=own.id,created_by=owner.id)
    chapter = await Chapter.create(novel=novel,number=1,name='Episode',content='Script')
    scene = await Scene.create(chapter=chapter,sequence=1)
    viewer_headers = _auth(await _login(client,viewer.username))
    foreign_headers = _auth(await _login(client,stranger.username))
    url=f'/api/scene/{scene.id}/storyboard-sheet'
    assert (await client.get(url+'/history',headers=viewer_headers)).json()['code']==0
    assert (await client.get(url+'/history',headers=foreign_headers)).json()['code'] in (403,404)
    for suffix,payload in [('edit',{'instruction':'Edit the sheet','expected_revision':'revision'}),
                           ('restore',{'task_id':str(uuid4()),'expected_revision':'revision'})]:
        assert (await client.post(url+'/'+suffix,json=payload,headers=viewer_headers)).json()['code']==403
        assert (await client.post(url+'/'+suffix,json=payload,headers=foreign_headers)).json()['code'] in (403,404)
