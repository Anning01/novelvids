import pytest
from auth.models import Team
from config import settings
from models.resource_library import VideoResource
from models.audio_reference import AudioReference
from test.test_auth.test_team_scoping import _create_member, _login, _auth

pytestmark=pytest.mark.skipif(not settings.AUTH_ENABLED,reason='AUTH_ENABLED=true permission suite')


@pytest.mark.asyncio
async def test_catalog_team_ids_cannot_bypass_read_or_write_scope(client):
    team=await Team.create(name='Catalog team')
    other=await Team.create(name='Catalog other')
    creator,_=await _create_member('catalog_creator',team)
    viewer,_=await _create_member('catalog_viewer',team,role='viewer')
    outsider,_=await _create_member('catalog_outsider',other)
    media=await VideoResource.create(team_id=team.id,name='BGM',kind='bgm',filename='music.wav',storage_ref='/music.wav',state='ready')
    for user,visible,write in ((creator,True,0),(viewer,True,403),(outsider,False,404)):
        headers=_auth(await _login(client,user.username))
        data=(await client.get('/api/resource-library/catalog?kind=bgm',headers=headers)).json()
        assert data['code']==0
        assert bool(data['data']['items'])==visible
        assert (await client.get(f'/api/resource-library/catalog/media:{media.id}',headers=headers)).json()['code']==(0 if visible else 404)
        assert (await client.patch(f'/api/resource-library/catalog/media:{media.id}',headers=headers,json={'name':'renamed'})).json()['code']==write
    assert (await client.get('/api/resource-library/catalog')).json()['code']==401


@pytest.mark.asyncio
async def test_personal_voice_and_builtin_identity_are_preserved(client):
    team=await Team.create(name='Voice catalog')
    creator,_=await _create_member('catalog_voice_creator',team)
    outsider,_=await _create_member('catalog_voice_outsider',team)
    voice=await AudioReference.create(nickname='Private voice',gender='男',asset_id='personal-original-id',audio_url='/voice.wav',avatar_url='',source='upload',created_by=creator.id)
    headers=_auth(await _login(client,outsider.username))
    assert (await client.get(f'/api/resource-library/catalog/voice:{voice.id}',headers=headers)).json()['code']==404
    headers=_auth(await _login(client,creator.username))
    response=(await client.get('/api/resource-library/catalog?kind=voice',headers=headers)).json()
    assert response['data']['items'][0]['payload']['asset_id']=='personal-original-id'
    assert response['data']['items'][0]['origin']=='personal'
    assert (await client.post('/api/resource-library/catalog/move',headers=headers,json={'keys':[f'voice:{voice.id}'],'folder_id':0})).json()['code']==403


@pytest.mark.asyncio
async def test_cross_team_media_and_voice_cannot_be_applied_or_saved_in_a_draft(client):
    from models.novel import Novel
    from models.chapter import Chapter
    from models.video_edit import ChapterEditDraft
    from models.resource_library import ProjectResource,ResourcePlacement
    first=await Team.create(name='Catalog own team')
    second=await Team.create(name='Catalog foreign team')
    creator,_=await _create_member('catalog_target_creator',first)
    viewer,_=await _create_member('catalog_target_viewer',first,role='viewer')
    novel=await Novel.create(name='Catalog own project',team_id=first.id)
    chapter=await Chapter.create(novel=novel,number=1,name='One',content='')
    media=await VideoResource.create(team_id=second.id,name='Foreign BGM',kind='bgm',filename='a.wav',storage_ref='/media/a.wav',state='ready',media={'duration':3})
    headers=_auth(await _login(client,creator.username))
    assert (await client.post(f'/api/resource-library/catalog/media:{media.id}/apply',json={'novel_id':novel.id},headers=headers)).json()['code']==404
    payload={'revision':0,'document':{'clips':[{'id':'audio','type':'audio','start':0,'duration':2,'source':{'kind':'library','id':media.id}}]}}
    assert (await client.put(f'/api/video-editor/chapters/{chapter.id}',json=payload,headers=headers)).json()['code']==404
    assert not await ChapterEditDraft.all().exists() and not await ProjectResource.all().exists()
    own=await VideoResource.create(team_id=first.id,name='Own BGM',kind='bgm',filename='b.wav',storage_ref='/media/b.wav',state='ready',media={'duration':3})
    headers=_auth(await _login(client,viewer.username))
    assert (await client.post(f'/api/resource-library/catalog/media:{own.id}/apply',json={'novel_id':novel.id},headers=headers)).json()['code']==403
    assert (await client.post('/api/resource-library/catalog/upload-policy',json={'filename':'music.wav','kind':'bgm'},headers=headers)).json()['code']==403
    assert (await client.post('/api/resource-library/catalog/voices/upload',data={'nickname':'voice'},files={'file':('a.wav',b'bad','audio/wav')},headers=headers)).json()['code']==403
    assert not await ResourcePlacement.all().exists()
