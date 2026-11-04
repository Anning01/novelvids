import io
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from auth.deps import AuthContext
from config import settings
from controllers.resource_library import resource_library_controller as library
from models.audio_reference import AudioReference
from models.digital_human import DigitalHuman
from models.resource_library import VideoResource
from schemas.resource_library import FolderWrite
from services.resource_catalog import resource_catalog
from services.resource_storage import resource_storage, library_media_storage
from services.oss.base import LocalProvider


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)
    monkeypatch.setattr('services.resource_storage.oss', LocalProvider())


@pytest.mark.asyncio
async def test_old_video_and_new_bgm_stable_ids_and_folder():
    old = await library.reserve(4, None, 'old.mp4')
    old.state = 'ready'; await old.save()
    music = await library.reserve(4, None, 'music.wav', kind='bgm')
    music.state = 'ready'; music.media = {'duration': 3}; await music.save()
    folder = await library.write_folder(4, None, FolderWrite(name='共享'))
    before = music.storage_ref
    await library.move(4, [old.id, music.id], folder.id)
    await music.refresh_from_db()
    assert music.storage_ref == before
    result = await resource_catalog.list(4, AuthContext(), kind='all')
    assert {i['kind'] for i in result['items']} >= {'video', 'bgm'}
    from services.resource_references import resource_for
    with pytest.raises(HTTPException):
        await resource_for(4, music.id)
    assert (await resource_for(4, music.id, kind=None)).id == music.id
    assert (await resource_for(4, old.id)).id == old.id


@pytest.mark.asyncio
async def test_old_voice_and_character_ids_remain_distinct_and_private_voice_not_published():
    voice = await AudioReference.create(nickname='系统', gender='男', audio_url='/a.wav', avatar_url='', asset_id='voice', source='system')
    private = await AudioReference.create(nickname='个人', gender='女', audio_url='/p.wav', avatar_url='', asset_id='private', source='upload', created_by=901)
    team = await AudioReference.create(nickname='团队', gender='女', audio_url='/t.wav', avatar_url='', asset_id='team', source='upload', team_id=5)
    human = await DigitalHuman.create(country='中国', age=20, gender='男', occupation='学生', asset_id='human', image_url='/human.png')
    data = await resource_catalog.list(5, AuthContext(), kind='all')
    keys = {i['key'] for i in data['items']}
    assert f'voice:{voice.id}' in keys and f'human:{human.id}' in keys
    assert f'voice:{team.id}' in keys and f'voice:{private.id}' not in keys
    with pytest.raises(HTTPException):
        await resource_catalog.rename(5, AuthContext(), f'voice:{voice.id}', '不能改')
    await resource_catalog.rename(5, AuthContext(), f'voice:{team.id}', '新名称')
    await team.refresh_from_db()
    assert team.nickname == '新名称' and team.asset_id == 'team'


@pytest.mark.asyncio
async def test_real_audio_and_sticker_upload_inspection_and_wrong_kind(tmp_path):
    audio = tmp_path/'sound.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1','-y',str(audio)],check=True)
    image = tmp_path/'sticker.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=64x64','-frames:v','1','-y',str(image)],check=True)
    for filename, kind in [(audio,'bgm'), (audio,'sound'), (image,'sticker'), (image,'image')]:
        row = await library.reserve(0, None, filename.name, kind=kind)
        await library_media_storage.upload(row.storage_ref, UploadFile(filename=filename.name,file=io.BytesIO(filename.read_bytes())))
        row = await library.finalize(0,row.id)
        assert row.state == 'ready' and row.kind == kind
        assert row.media['size_bytes'] == filename.stat().st_size
    fake = await library.reserve(0,None,'fake.png',kind='sticker')
    await library_media_storage.put(fake.storage_ref,audio,'image/png')
    with pytest.raises(HTTPException):
        await library.finalize(0,fake.id)


@pytest.mark.asyncio
async def test_kind_folder_search_are_combined_and_cross_team_move_is_rejected():
    folder = await library.write_folder(1,None,FolderWrite(name='音乐'))
    first = await VideoResource.create(team_id=1,folder_id=folder.id,name='同名',kind='bgm',filename='a.wav',storage_ref='/a.wav',state='ready')
    await VideoResource.create(team_id=1,name='同名',kind='video',filename='a.mp4',storage_ref='/a.mp4',state='ready')
    await VideoResource.create(team_id=2,name='同名',kind='bgm',filename='a.wav',storage_ref='/a.wav',state='ready')
    result = await resource_catalog.list(1,AuthContext(),kind='bgm',folder_id=folder.id,search='同名')
    assert result['pagination']['total'] == 1 and result['items'][0]['id'] == first.id
    with pytest.raises(HTTPException):
        await resource_catalog.move(2,AuthContext(),[f'media:{first.id}'],0)


@pytest.mark.asyncio
async def test_same_team_projects_reuse_media_without_copying_and_keep_old_video_contract():
    from models.novel import Novel
    from models.chapter import Chapter
    from models.resource_library import ProjectResource
    from schemas.resource_library import CatalogApply
    from services.catalog_applications import apply_catalog_resource
    from services.video_editor.sources import EditSources
    first=await Novel.create(name='项目一',team_id=6)
    second=await Novel.create(name='项目二',team_id=6)
    a=await Chapter.create(novel=first,number=1,name='一',content='')
    b=await Chapter.create(novel=second,number=1,name='一',content='')
    resource=await VideoResource.create(team_id=6,name='配乐',kind='bgm',filename='bgm.wav',storage_ref='/media/original.wav',state='ready',media={'duration':4})
    for novel,chapter in ((first,a),(second,b)):
        await apply_catalog_resource(6,AuthContext(),f'media:{resource.id}',CatalogApply(novel_id=novel.id))
        await apply_catalog_resource(6,AuthContext(),f'media:{resource.id}',CatalogApply(novel_id=novel.id))
        media=await EditSources(novel.id,chapter.id).catalog()
        assert media[0]['source']=={'kind':'library','id':resource.id}
        assert media[0]['kind']=='audio' and media[0]['ref']=='/media/original.wav'
    assert await ProjectResource.all().count()==2
    assert await VideoResource.all().count()==1
    other=await Novel.create(name='别的团队',team_id=7)
    with pytest.raises(HTTPException):
        await apply_catalog_resource(6,AuthContext(),f'media:{resource.id}',CatalogApply(novel_id=other.id))


@pytest.mark.asyncio
async def test_publish_and_reuse_role_preserves_variants_and_voice_ids():
    from models.novel import Novel
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from schemas.resource_library import CatalogApply
    from services.catalog_applications import apply_catalog_resource
    source=await Novel.create(name='角色来源',team_id=2)
    target=await Novel.create(name='角色目标',team_id=2)
    voice=await AudioReference.create(nickname='角色声音',gender='男',audio_url='/v.wav',avatar_url='',asset_id='keep-voice-id',source='upload',team_id=2)
    asset=await Asset.create(novel=source,asset_type=1,canonical_name='苏玄',base_traits='保存的完整提示词',main_image='/media/hero.png',metadata={'voice_reference_id':voice.id})
    variant=await AssetVariant.create(asset=asset,name='少年',base_traits='原形态提示词',images=['/media/young.png'],metadata={'voice_reference_id':voice.id})
    result=await resource_catalog.publish_asset(2,AuthContext(),asset.id)
    assert result['key']==f'asset:{asset.id}'
    response=await apply_catalog_resource(2,AuthContext(),result['key'],CatalogApply(novel_id=target.id))
    again=await apply_catalog_resource(2,AuthContext(),result['key'],CatalogApply(novel_id=target.id))
    assert response['asset_id']==again['asset_id']
    copied=await Asset.get(id=response['asset_id'])
    assert copied.base_traits==asset.base_traits and copied.metadata['voice_reference_id']==voice.id
    copied_variant=await AssetVariant.get(asset_id=copied.id)
    assert copied_variant.base_traits==variant.base_traits and copied_variant.metadata['voice_reference_id']==voice.id
    await asset.refresh_from_db();await voice.refresh_from_db()
    assert voice.asset_id=='keep-voice-id' and asset.id==result['id']


@pytest.mark.asyncio
async def test_binding_voice_checks_project_and_target_variant():
    from models.novel import Novel
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from schemas.resource_library import CatalogApply
    from services.catalog_applications import apply_catalog_resource
    novel=await Novel.create(name='绑定目标',team_id=1)
    asset=await Asset.create(novel=novel,asset_type=1,canonical_name='角色',metadata={'keep':True})
    variant=await AssetVariant.create(asset=asset,name='变体',metadata={'keep_variant':True,'editor_form':{'voice_reference_id':900,'prompt':'keep'}})
    voice=await AudioReference.create(nickname='音色',gender='男',asset_id='voice-identity',audio_url='/a.wav',avatar_url='',source='upload',team_id=1)
    await apply_catalog_resource(1,AuthContext(),f'voice:{voice.id}',CatalogApply(novel_id=novel.id,asset_id=asset.id,variant_id=variant.id))
    await variant.refresh_from_db()
    assert variant.metadata=={'keep_variant':True,'voice':'音色','voice_reference_id':voice.id,'editor_form':{'voice_reference_id':voice.id,'voice':'音色','prompt':'keep'}}
    await apply_catalog_resource(1,AuthContext(),f'voice:{voice.id}',CatalogApply(novel_id=novel.id))
    await novel.refresh_from_db()
    assert novel.narrator_audio_reference_id==voice.id


@pytest.mark.asyncio
async def test_image_reference_capabilities_and_kind_cannot_be_forged():
    from services.resource_references import validate_resource_model, reference_dict
    from services.video.capabilities import capabilities_for
    row=await VideoResource.create(team_id=0,name='图片',kind='image',filename='image.png',storage_ref='/image.png',state='ready',media={'size_bytes':100,'_probe':{'streams':[{'codec_type':'video','codec_name':'png','width':1280,'height':720}]}})
    caps=capabilities_for('seedance_2')
    validate_resource_model(row,caps)
    assert reference_dict(row)['type']=='image'
    row.kind='bgm'
    with pytest.raises(HTTPException):
        validate_resource_model(row,caps)


@pytest.mark.asyncio
async def test_catalog_schema_addition_preserves_legacy_video_rows_and_is_repeatable():
    # Only the isolated in-memory test database is changed to simulate the old schema.
    import re
    from tortoise import Tortoise
    from services.schema_compat import ensure_resource_library_schema
    row=await VideoResource.create(team_id=9,name='旧视频',filename='old.mp4',storage_ref='/media/keep.mp4',state='ready')
    connection=Tortoise.get_connection('default')
    for index in await connection.execute_query_dict('PRAGMA index_list(video_resources)'):
        name=index['name']
        assert re.fullmatch(r'[A-Za-z0-9_]+',name)
        columns=await connection.execute_query_dict(f'PRAGMA index_info("{name}")')
        if any(column['name']=='kind' for column in columns):
            await connection.execute_script(f'DROP INDEX "{name}";')
    await connection.execute_script('ALTER TABLE video_resources DROP COLUMN kind;')
    for _ in range(2):
        await ensure_resource_library_schema()
    await row.refresh_from_db()
    assert row.kind=='video' and row.storage_ref=='/media/keep.mp4' and row.name=='旧视频'


@pytest.mark.asyncio
async def test_repeated_project_upload_publication_reuses_one_library_file(tmp_path):
    from models.novel import Novel
    from models.video_edit import EditorAsset
    from services.catalog_publication import publish_editor_resource
    from schemas.resource_library import CatalogPublish
    path=tmp_path/'original.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=220:duration=1','-y',str(path)],check=True)
    novel=await Novel.create(name='素材存入测试')
    source=await EditorAsset.create(novel=novel,kind='audio',name='original.wav',media_ref='/media/original.wav',sha256='a'*64)
    payload=CatalogPublish(catalog='editor',source_id=source.id,kind='bgm')
    first=await publish_editor_resource(0,AuthContext(),payload)
    second=await publish_editor_resource(0,AuthContext(),payload)
    assert first['key']==second['key']
    assert await VideoResource.all().count()==1


@pytest.mark.asyncio
async def test_published_role_alias_search_and_traits_combine_with_system_filters():
    from models.novel import Novel
    from models.asset import Asset
    from models.resource_library import ResourcePlacement
    novel=await Novel.create(name='筛选来源',team_id=4)
    asset=await Asset.create(novel=novel,asset_type=1,canonical_name='原名',metadata={'gender':'男','country':'中国','age':18,'occupation':'学生'})
    await resource_catalog.publish_asset(4,AuthContext(),asset.id)
    await resource_catalog.rename(4,AuthContext(),f'asset:{asset.id}','目录别名')
    result=await resource_catalog.list(4,AuthContext(),kind='character',search='目录别名',gender='male',country='中国',age='under-20',occupation='学生',sort='name')
    assert result['pagination']['total']==1 and result['items'][0]['name']=='目录别名'
    assert result['items'][0]['age']==18
    result=await resource_catalog.list(4,AuthContext(),kind='character',gender='female')
    assert result['pagination']['total']==0
    for age in ['20-29','30-39','40-59','60-plus']:
        assert not (await resource_catalog.list(4,AuthContext(),kind='character',age=age))['items']
    await asset.refresh_from_db()
    assert asset.canonical_name=='原名'


@pytest.mark.asyncio
async def test_voice_folder_placement_and_readonly_builtin_move_are_atomic():
    from models.resource_library import ResourcePlacement
    one=await AudioReference.create(nickname='自有',gender='男',asset_id='movable-voice',audio_url='/v.wav',avatar_url='',source='upload',team_id=3)
    system=await AudioReference.create(nickname='系统',gender='男',asset_id='unmovable-voice',audio_url='/s.wav',avatar_url='',source='system')
    folder=await library.write_folder(3,None,FolderWrite(name='声音'))
    with pytest.raises(HTTPException):
        await resource_catalog.move(3,AuthContext(),[f'voice:{one.id}',f'voice:{system.id}'],folder.id)
    assert not await ResourcePlacement.all().exists()
    await resource_catalog.move(3,AuthContext(),[f'voice:{one.id}'],folder.id)
    assert (await resource_catalog.list(3,AuthContext(),kind='voice',folder_id=folder.id,origin='team'))['pagination']['total']==1
    assert (await resource_catalog.list(3,AuthContext(),kind='voice',folder_id=0,origin='team'))['pagination']['total']==0
    with pytest.raises(HTTPException):
        await library.delete_folder(3,folder.id)
    await resource_catalog.move(3,AuthContext(),[f'voice:{one.id}'],0)
    assert (await resource_catalog.list(3,AuthContext(),kind='voice',folder_id=0,origin='team'))['pagination']['total']==1


@pytest.mark.asyncio
async def test_builtin_character_apply_and_private_voice_conflicts_preserve_source_data():
    from models.novel import Novel
    from models.asset import Asset
    from schemas.resource_library import CatalogApply
    from services.catalog_applications import apply_catalog_resource
    first=await Novel.create(name='公共角色来源',team_id=5,created_by=101)
    target=await Novel.create(name='公共角色目标',team_id=5,created_by=102)
    human=await DigitalHuman.create(country='中国',age=30,gender='男',occupation='修士',asset_id='stable-human-id',image_url='/human.png')
    result=await apply_catalog_resource(5,AuthContext(),f'human:{human.id}',CatalogApply(novel_id=target.id,canonical_name='新角色名'))
    assert (await Asset.get(id=result['asset_id'])).metadata['source_asset_id']=='stable-human-id'
    voice=await AudioReference.create(nickname='个人',gender='男',asset_id='own-private-voice',audio_url='/v.wav',avatar_url='',source='upload',created_by=101)
    asset=await Asset.create(novel=first,asset_type=1,canonical_name='私有音色角色',metadata={'voice_reference_id':voice.id})
    await resource_catalog.publish_asset(5,AuthContext(),asset.id)
    with pytest.raises(HTTPException):
        await apply_catalog_resource(5,AuthContext(),f'asset:{asset.id}',CatalogApply(novel_id=target.id))
    assert not await Asset.filter(novel=target,canonical_name=asset.canonical_name).exists()


@pytest.mark.asyncio
async def test_catalog_api_real_upload_get_rename_move_and_validation(client,tmp_path):
    path=tmp_path/'api.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=220:duration=1','-y',str(path)],check=True)
    assert (await client.get('/api/resource-library/catalog/capabilities')).json()['data']['kinds']['bgm']['formats']==['mp3','wav','m4a']
    assert (await client.post('/api/resource-library/catalog/upload-policy',json={'kind':'bgm','filename':'api.wav'})).json()['data']=={'direct':False}
    response=(await client.post('/api/resource-library/catalog/upload',data={'kind':'sound'},files={'file':('api.wav',path.read_bytes(),'audio/wav')})).json()
    assert response['code']==0
    key=response['data']['key']
    assert (await client.get('/api/resource-library/catalog/'+key)).json()['data']['kind']=='sound'
    assert (await client.patch('/api/resource-library/catalog/'+key,json={'name':'声音改名'})).json()['data']['name']=='声音改名'
    assert (await client.post('/api/resource-library/catalog/move',json={'keys':[key],'folder_id':0})).json()['code']==0
    assert (await client.get('/api/resource-library/catalog/bogus:1')).json()['code']==422
    assert (await client.post('/api/resource-library/catalog/upload',data={'kind':'sticker'},files={'file':('fake.png',b'not an image','image/png')})).json()['code']==422
    assert (await client.post('/api/resource-library/catalog/upload',data={'kind':'video'},files={'file':('api.wav',path.read_bytes(),'audio/wav')})).json()['code']!=0
    assert (await client.post('/api/resource-library/catalog/voices/upload',data={'nickname':'团队音色','gender':'男'},files={'file':('api.wav',path.read_bytes(),'audio/wav')})).json()['code']==0


@pytest.mark.asyncio
async def test_catalog_oss_upload_finalization_keeps_kind_and_does_not_duplicate(client,tmp_path,monkeypatch):
    path=tmp_path/'upload.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=300:duration=1','-y',str(path)],check=True)
    class Storage:
        enabled=True
        def sign_form_upload(self,key,mime,size):
            assert key.startswith('uploads/0/') and mime=='audio/x-wav'
            return {'url':'https://storage.invalid','fields':{'key':key}}
        async def download_to_file(self,key,destination):
            destination.write_bytes(path.read_bytes())
        async def delete(self,key):
            pass
    storage=Storage()
    monkeypatch.setattr('api.resource_catalog.oss',storage)
    monkeypatch.setattr('services.resource_storage.oss',storage)
    ticket=(await client.post('/api/resource-library/catalog/upload-policy',json={'filename':'music.wav','kind':'bgm'})).json()['data']
    assert ticket['direct']
    for _ in range(2):
        response=(await client.post(f'/api/resource-library/catalog/resources/{ticket["resource_id"]}/finalize')).json()
        assert response['code']==0 and response['data']['kind']=='bgm'
    assert await VideoResource.all().count()==1
