from datetime import datetime, timezone

import pytest

from auth.models import Team, TeamMember, User
from config import settings
from models.novel import Novel
from models.chapter import Chapter
from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from services.video_enhancement.media import export_media
from test.test_auth.test_team_scoping import _create_member, _login, _auth
from test.test_services.test_video_editor import ffmpeg

pytestmark=pytest.mark.skipif(not settings.AUTH_ENABLED,reason='AUTH_ENABLED=true permission suite')


async def completed(chapter,revision,ref=None):
    task=await AiTask.create(task_type=4,status=3,stage='completed',request_params={'operation':'editor_render'},finished_at=datetime.now(timezone.utc))
    return await ChapterExport.create(novel_id=chapter.novel_id,chapter_id=chapter.id,task=task,identity_key=f'{chapter.id}-{revision}',source_version='fixed',
        recipe={'kind':'editor_render','revision':revision},collection_complete=True,media_ref=ref or f'/media/exports/{chapter.id}/{revision}.mp4',
        output_probe={'duration':1,'width':160,'height':90,'fps':24})


@pytest.mark.asyncio
async def test_version_specific_publication_and_revocation_enforce_team_and_role_permissions(client,tmp_path,monkeypatch):
    monkeypatch.setattr('config.settings.MEDIA_PATH',str(tmp_path/'media'))
    monkeypatch.setattr('config.settings.CHAPTER_EXPORT_PATH',str(tmp_path/'private'))
    team=await Team.create(name='Owners',balance=1)
    other=await Team.create(name='Audience',balance=1)
    admin,_=await _create_member('finished_admin',team,role='admin')
    creator,_=await _create_member('finished_creator',team)
    viewer,_=await _create_member('finished_viewer',team,role='viewer')
    outsider,_=await _create_member('finished_outsider',other)
    boss=await User.create(username='finished_super',is_super_admin=True)
    headers={user.username:_auth(await _login(client,user.username)) for user in [admin,creator,viewer,outsider,boss]}
    a,c,v,o,b=[headers[user.username] for user in [admin,creator,viewer,outsider,boss]]
    project=await Novel.create(name='Private original',team_id=team.id)
    chapter=await Chapter.create(novel=project,number=1,name='Episode',content='')
    first=await completed(chapter,1)
    source=tmp_path/'video.mp4'
    ffmpeg('-f','lavfi','-i','color=c=red:s=160x90:r=24:d=1','-c:v','libx264','-pix_fmt','yuv420p',source)
    await export_media.store(first.media_ref,source)
    assert (await client.get('/api/finished-episodes')).json()['code']==401
    assert (await client.get(f'/api/finished-episodes/versions/{first.id}/cover')).json()['code']==401
    assert (await client.get('/api/finished-episodes',headers=o)).json()['data']['total']==0
    assert (await client.get('/api/finished-episodes',headers=v)).json()['data']['total']==1
    assert (await client.get(f'/api/finished-episodes/chapters/{chapter.id}/versions',headers=o)).json()['code']==404
    path=f'/api/finished-episodes/chapters/{chapter.id}/publication'
    for forbidden in [c,v]:
        assert (await client.put(path,json={'export_id':first.id},headers=forbidden)).json()['code']==403
    assert (await client.put(path,json={'export_id':first.id},headers=o)).json()['code']==403
    assert (await client.put(path,json={'export_id':first.id},headers=a)).json()['code']==0
    second=await completed(chapter,2)
    own=(await client.get('/api/finished-episodes',headers=a)).json()['data']['items'][0]
    public=(await client.get('/api/finished-episodes?scope=published',headers=o)).json()['data']['items'][0]
    assert own['version']['id']==second.id and public['version']['id']==first.id
    assert not public['can_publish'] and not public['can_feature']
    public_versions=(await client.get(f'/api/finished-episodes/chapters/{chapter.id}/versions',headers=o)).json()['data']
    assert [row['id'] for row in public_versions]==[first.id]
    assert (await client.get(f'/api/finished-episodes/versions/{second.id}/video',headers=o)).json()['code']==404
    image=await client.get(f'/api/finished-episodes/versions/{first.id}/cover',headers=o)
    assert image.headers['content-type']=='image/jpeg' and image.content.startswith(b'\xff\xd8')
    data=await client.get(f'/api/finished-episodes/versions/{first.id}/video',headers={**o,'Range':'bytes=0-15'})
    assert data.status_code==206 and len(data.content)==16
    feature=f'/api/finished-episodes/chapters/{chapter.id}/featured'
    assert (await client.put(feature,json={'export_id':first.id,'featured':True},headers=a)).json()['code']==403
    assert (await client.put(feature,json={'export_id':first.id,'featured':True},headers=b)).json()['code']==0
    assert (await client.get('/api/finished-episodes?scope=featured',headers=o)).json()['data']['total']==1
    assert (await client.put(path,json={'export_id':second.id,'expected_id':first.id},headers=a)).json()['code']==0
    assert (await client.get('/api/finished-episodes?scope=featured',headers=o)).json()['data']['total']==0
    assert (await client.put(path,json={'export_id':first.id,'expected_id':first.id},headers=a)).json()['code']==409
    assert (await client.put(path,json={'export_id':None,'expected_id':second.id},headers=a)).json()['code']==0
    assert (await client.get(f'/api/finished-episodes/versions/{first.id}/cover',headers=o)).json()['code']==404
    assert (await client.get(f'/api/finished-episodes/versions/{first.id}/video',headers=o)).json()['code']==404


@pytest.mark.asyncio
async def test_published_library_is_available_to_accounts_without_team_membership(client):
    team=await Team.create(name='Publisher',balance=1)
    admin,_=await _create_member('finished_owner',team,role='admin')
    outsider,_=await _create_member('finished_no_team',team,role='viewer')
    await TeamMember.filter(user_id=outsider.id).delete()
    project=await Novel.create(name='Public episode',team_id=team.id)
    chapter=await Chapter.create(novel=project,number=1,name='Episode',content='')
    row=await completed(chapter,1)
    admin_headers=_auth(await _login(client,admin.username))
    outsider_headers=_auth(await _login(client,outsider.username))
    assert (await client.put(f'/api/finished-episodes/chapters/{chapter.id}/publication',json={'export_id':row.id},headers=admin_headers)).json()['code']==0
    assert (await client.get('/api/finished-episodes?scope=published',headers=outsider_headers)).json()['data']['total']==1
    assert (await client.get('/api/finished-episodes',headers=outsider_headers)).json()['data']['total']==0
