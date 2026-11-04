import pytest
from auth.models import Team
from config import settings
from models.novel import Novel
from models.chapter import Chapter
from models.video_edit import ChapterEditDraft, EditorAsset
from test.test_auth.test_team_scoping import _create_member, _login, _auth

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason='AUTH_ENABLED=true permission suite')


@pytest.mark.asyncio
async def test_editor_preserves_team_isolation_and_read_only_roles(client):
    team=await Team.create(name='Editor team',balance=0)
    other=await Team.create(name='Editor other',balance=0)
    creator,_=await _create_member('edit_creator',team)
    viewer,_=await _create_member('edit_viewer',team,role='viewer')
    outsider,_=await _create_member('edit_outsider',other)
    novel=await Novel.create(name='Editor scope',team_id=team.id)
    chapter=await Chapter.create(novel=novel,number=1,name='First',content='')
    payload={'revision':0,'document':{'clips':[]}}
    for user,read,write in ((creator,0,0),(viewer,0,403),(outsider,404,404)):
        headers=_auth(await _login(client,user.username))
        assert (await client.get(f'/api/video-editor/chapters/{chapter.id}',headers=headers)).json()['code']==read
        body={**payload,'revision':1 if await ChapterEditDraft.all().exists() else 0}
        assert (await client.put(f'/api/video-editor/chapters/{chapter.id}',json=body,headers=headers)).json()['code']==write
        if write:
            assert (await client.post(f'/api/video-editor/chapters/{chapter.id}/exports',json={'revision':1},headers=headers)).json()['code']==write
            assert (await client.post(f'/api/video-editor/chapters/{chapter.id}/assets?kind=audio',
                files={'file':('test.mp3',b'x','audio/mpeg')},headers=headers)).json()['code']==write
    assert (await client.get(f'/api/video-editor/chapters/{chapter.id}')).json()['code']==401
    assert await ChapterEditDraft.all().count()==1 and not await EditorAsset.all().exists()


@pytest.mark.asyncio
async def test_another_project_asset_cannot_be_bound_by_guessing_its_id(client):
    team=await Team.create(name='Asset scope',balance=0)
    creator,_=await _create_member('edit_asset_creator',team)
    first=await Novel.create(name='First project',team_id=team.id)
    other=await Novel.create(name='Other project',team_id=team.id)
    chapter=await Chapter.create(novel=first,number=1,name='Chapter',content='')
    asset=await EditorAsset.create(novel=other,kind='audio',name='private.mp3',media_ref='/media/private.mp3',
        sha256='a'*64,probe={'duration':2})
    payload={'revision':0,'document':{'clips':[{'id':'audio','type':'audio','start':0,'duration':1,
        'source':{'kind':'asset','id':asset.id}}]}}
    response=await client.put(f'/api/video-editor/chapters/{chapter.id}',json=payload,
        headers=_auth(await _login(client,creator.username)))
    assert response.json()['code']==404
    assert not await ChapterEditDraft.all().exists()
