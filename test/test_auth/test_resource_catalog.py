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


async def _super_headers(client):
    from auth.models import User
    from auth.security import hash_password
    user = await User.create(username='catalog_super', password_hash=hash_password('password123'), is_super_admin=True)
    return user, _auth(await _login(client, user.username))


@pytest.mark.asyncio
async def test_super_admin_can_browse_all_projects_and_manage_public_seeds_without_team(client):
    from models.novel import Novel
    from models.digital_human import DigitalHuman
    boss, headers = await _super_headers(client)
    first = await Team.create(name='All resources one')
    second = await Team.create(name='All resources two')
    for team in (first, second):
        await Novel.create(name=team.name, team_id=team.id)
        await VideoResource.create(team_id=team.id, name=team.name, filename='a.mp4', storage_ref='/a.mp4', state='ready')
    voice = await AudioReference.create(nickname='Public voice', gender='男', asset_id='public-voice', audio_url='/voice.wav', avatar_url='')
    human = await DigitalHuman.create(country='中国', age=20, gender='女', occupation='Public character', asset_id='public-human', image_url='/human.jpg')
    private_voice = await AudioReference.create(nickname='Second team voice', gender='男', asset_id='private-team-voice', audio_url='/private.wav', avatar_url='', source='upload', team_id=second.id)
    data = (await client.get('/api/resource-library/catalog', headers=headers)).json()
    assert data['code'] == 0, data
    assert len(data['data']['items']) == 5
    assert all(row['editable'] and row['deletable'] for row in data['data']['items'])
    projects = (await client.get('/api/resource-library/catalog/projects', headers=headers)).json()
    assert projects['data']['pagination']['total'] == 2
    scoped = {**headers, 'X-Team-Id':str(first.id)}
    assert (await client.get('/api/resource-library/catalog/projects', headers=scoped)).json()['data']['pagination']['total'] == 1
    listing = (await client.get('/api/resource-library/catalog', headers=scoped)).json()
    assert listing['code'] == 0 and len(listing['data']['items']) == 3
    assert all(row['key'] != f'voice:{private_voice.id}' for row in listing['data']['items'])
    assert (await client.get('/api/resource-library/catalog', headers={**headers, 'X-Team-Id':'invalid'})).json()['code'] == 400
    for key in (f'voice:{voice.id}', f'human:{human.id}'):
        response = (await client.patch(f'/api/resource-library/catalog/{key}', headers=headers, json={'name':'Managed by platform'})).json()
        assert response['code'] == 0, response
        response = (await client.post('/api/resource-library/catalog/delete', headers=headers, json={'keys':[key]})).json()
        assert response['code'] == 0, response
    assert not (await AudioReference.get(id=voice.id)).is_active
    assert not (await DigitalHuman.get(id=human.id)).is_active


@pytest.mark.asyncio
async def test_public_uploads_are_usable_but_protected_from_team_admin_and_creator(client, monkeypatch):
    from models.novel import Novel
    from services.resource_storage import resource_storage
    from unittest.mock import AsyncMock
    boss, boss_headers = await _super_headers(client)
    team = await Team.create(name='Protected originals')
    other = await Team.create(name='Other originals')
    admin, _ = await _create_member('public_team_admin', team, role='admin')
    creator, _ = await _create_member('public_team_creator', team)
    novel = await Novel.create(name='Public consumer', team_id=team.id, created_by=creator.id)
    # Historical super uploads retain their existing team and IDs, yet are public.
    media = await VideoResource.create(team_id=other.id, created_by=boss.id, name='Public music', kind='bgm', filename='a.wav', storage_ref='/public.wav', state='ready')
    voice = await AudioReference.create(nickname='Historical public voice', gender='男', asset_id='public-legacy', audio_url='/voice.wav', avatar_url='', source='upload', created_by=boss.id)
    private = await VideoResource.create(team_id=other.id, name='Private music', kind='bgm', filename='private.wav', storage_ref='/private.wav', state='ready')
    monkeypatch.setattr(resource_storage, 'delete', AsyncMock())
    for user in (admin, creator):
        headers = _auth(await _login(client, user.username))
        data = (await client.get('/api/resource-library/catalog', headers=headers)).json()
        assert data['code'] == 0, data
        entries = {row['key']:row for row in data['data']['items']}
        assert f'media:{private.id}' not in entries
        for key in (f'media:{media.id}', f'voice:{voice.id}'):
            assert entries[key]['is_public'] and not entries[key]['editable'] and not entries[key]['deletable']
            assert (await client.post(f'/api/resource-library/catalog/{key}/apply', headers=headers, json={'novel_id':novel.id})).json()['code'] == 0
            assert (await client.patch(f'/api/resource-library/catalog/{key}', headers=headers, json={'name':'forbidden'})).json()['code'] == 403
            assert (await client.post('/api/resource-library/catalog/delete', headers=headers, json={'keys':[key]})).json()['code'] == 403
        assert (await client.post('/api/resource-library/delete', headers=headers, json={'ids':[media.id]})).json()['code'] == 403
    assert not resource_storage.delete.called
    assert await VideoResource.filter(id=media.id, state='ready').exists()
    assert (await client.post('/api/resource-library/catalog/delete', headers=boss_headers, json={'keys':[f'media:{media.id}']})).json()['code'] == 0
    assert not await VideoResource.filter(id=media.id).exists()


@pytest.mark.asyncio
async def test_super_upload_policy_defaults_to_public_scope_and_batch_authorization_is_atomic(client, monkeypatch):
    from models.resource_library import ResourceFolder
    boss, boss_headers = await _super_headers(client)
    from types import SimpleNamespace
    monkeypatch.setattr('api.resource_catalog.oss', SimpleNamespace(enabled=True, sign_form_upload=lambda *args: {'url':'https://storage.invalid','fields':{}}))
    response = (await client.post('/api/resource-library/catalog/upload-policy', headers=boss_headers, json={'filename':'public.mp4','kind':'video'})).json()
    assert response['code'] == 0, response
    row = await VideoResource.get(id=response['data']['resource_id'])
    assert row.team_id == 0 and row.created_by == boss.id
    team = await Team.create(name='Protected folder team')
    admin, _ = await _create_member('folder_team_admin', team, role='admin')
    folder = await ResourceFolder.create(team_id=team.id, name='Mixed ownership')
    own = await VideoResource.create(team_id=team.id, created_by=admin.id, folder_id=folder.id, name='Own', filename='own.mp4', storage_ref='/own.mp4', state='ready')
    protected = await VideoResource.create(team_id=team.id, created_by=boss.id, folder_id=folder.id, name='Protected', filename='protected.mp4', storage_ref='/protected.mp4', state='ready')
    headers = _auth(await _login(client, admin.username))
    assert (await client.post('/api/resource-library/catalog/delete', headers=headers, json={'keys':[f'media:{own.id}',f'media:{protected.id}']})).json()['code'] == 403
    assert (await client.delete(f'/api/resource-library/folders/{folder.id}', headers=headers)).json()['code'] == 403
    assert await VideoResource.filter(id=own.id, state='ready').exists()
    assert await ResourceFolder.filter(id=folder.id, deleting=False).exists()


@pytest.mark.asyncio
async def test_public_project_asset_cannot_be_deleted_through_project_or_merge_endpoints(client):
    from models.novel import Novel
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.resource_library import ResourcePlacement
    from tortoise import Tortoise
    boss, boss_headers = await _super_headers(client)
    team = await Team.create(name='Public source project')
    admin, _ = await _create_member('public_source_admin', team, role='admin')
    source = await Novel.create(name='Platform source', team_id=team.id, created_by=boss.id)
    asset = await Asset.create(novel=source, asset_type=1, canonical_name='Public actor')
    target = await Asset.create(novel=source, asset_type=1, canonical_name='Merge target')
    variant = await AssetVariant.create(asset=asset, name='Default')
    await ResourcePlacement.create(team_id=team.id, catalog='asset', source_id=asset.id)
    headers = _auth(await _login(client, admin.username))
    for path in (f'/api/asset/{asset.id}', f'/api/asset/{asset.id}/variants/{variant.id}', f'/api/novel/{source.id}'):
        assert (await client.delete(path, headers=headers)).json()['code'] == 403
    assert (await client.post('/api/asset/merge', headers=headers, json={'source_asset_id':asset.id, 'target_asset_id':target.id})).json()['code'] == 403
    # Safe repeated schema creation preserves the original ownership and stable IDs.
    for _ in range(2):
        await Tortoise.generate_schemas(safe=True)
        listing = (await client.get('/api/resource-library/catalog', headers=boss_headers)).json()
        assert listing['code'] == 0, listing
        assert any(row['key'] == f'asset:{asset.id}' and row['editable'] for row in listing['data']['items'])
    assert await Asset.filter(id=asset.id).exists()
    assert (await client.delete(f'/api/asset/{asset.id}', headers=boss_headers)).json()['code'] == 0


@pytest.mark.asyncio
async def test_existing_public_seed_data_survives_repeated_startup(client):
    from models.digital_human import DigitalHuman
    from services.media_library_seed import ensure_media_library_seed_data
    boss, headers = await _super_headers(client)
    voice = await AudioReference.create(nickname='Existing seed', gender='女', asset_id='original-seed-voice', audio_url='/original.wav', avatar_url='')
    human = await DigitalHuman.create(country='中国', age=25, gender='女', occupation='Existing actor', asset_id='original-seed-human', image_url='/original.jpg')
    for _ in range(2):
        assert await ensure_media_library_seed_data() == {'audio_references':0, 'digital_humans':0}
        response = (await client.get('/api/resource-library/catalog', headers=headers)).json()
        assert response['code'] == 0, response
        assert {row['key'] for row in response['data']['items']} == {f'voice:{voice.id}', f'human:{human.id}'}
    assert await AudioReference.all().count() == await DigitalHuman.all().count() == 1
    assert (await AudioReference.get(id=voice.id)).audio_url == '/original.wav'
