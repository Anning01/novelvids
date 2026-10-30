from unittest.mock import AsyncMock

import pytest

from config import settings
from auth.models import Team
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.novel import Novel
from models.ai_task import AiTask
from test.test_auth.test_team_scoping import _create_member, _login, _auth

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason='AUTH_ENABLED=true permission suite')


@pytest.mark.asyncio
async def test_export_history_is_team_scoped_and_viewer_cannot_create_paid_operation(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path/'public-media'))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path/'private-exports'))
    team=await Team.create(name='export-team',balance=10)
    other=await Team.create(name='other-export-team',balance=10)
    owner,_=await _create_member('export-owner',team)
    viewer,_=await _create_member('export-viewer',team,role='viewer')
    outsider,_=await _create_member('export-outsider',other)
    novel=await Novel.create(name='Export source',team_id=team.id,created_by=owner.id)
    chapter=await Chapter.create(novel=novel,number=1,name='One',content='Fixture')
    export=await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,team_id=team.id,
        identity_key='a'*64,source_version='b'*64,source_media_ref='/media/exports/1/source.mp4')
    shared_task = await AiTask.create(task_type=8, status=2, request_params={'novel_id':novel.id,
        'team_id':team.id,'user_id':owner.id,'config_snapshot':{'pricing':{'private_price':123},'base_url':'https://private-service.example'}})
    from services.video_enhancement.media import export_media
    path = export_media.local_path(export.source_media_ref)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'private-source')
    assert not path.is_relative_to(tmp_path/'public-media')
    run=AsyncMock()
    monkeypatch.setattr('api.video_export.ai_task_executor.run',run)
    viewer_headers=_auth(await _login(client,viewer.username))
    outsider_headers=_auth(await _login(client,outsider.username))
    shared_status = (await client.get(f'/api/task/{shared_task.id}', headers=viewer_headers)).json()
    assert shared_status['code'] == 0
    assert 'config_snapshot' not in shared_status['data']['request_params']
    assert 'private_price' not in str(shared_status)
    assert (await client.get(f'/api/task/{shared_task.id}', headers=outsider_headers)).json()['code'] == 404
    assert (await client.get(f'/api/video/exports/{export.id}',headers=viewer_headers)).json()['code']==0
    for path in (f'/api/video/exports/{export.id}',f'/api/video/exports?chapter_id={chapter.id}',f'/api/video/exports/{export.id}/download?source=true'):
        response=await client.get(path,headers=outsider_headers)
        assert response.json()['code']==404
        assert 'private-source' not in response.text
    downloaded = await client.get(f'/api/video/exports/{export.id}/download?source=true', headers=viewer_headers)
    assert downloaded.status_code == 200 and downloaded.content == b'private-source'
    assert (await client.get(f'/api/video/exports/{export.id}/download?source=true')).json()['code'] == 401
    assert (await client.get(export.source_media_ref)).json()['code'] == 404
    response=await client.post('/api/video/exports',json={'chapter_id':chapter.id},headers=viewer_headers)
    assert response.json()['code']==403
    response=await client.post(f'/api/video/exports/{export.id}/enhance',json={
        'model_config_id':1,'source_sha256':'a'*64,'quote_version':'b'*64},headers=viewer_headers)
    assert response.json()['code']==403
    assert (await client.post(f'/api/video/exports/{export.id}/apply', headers=viewer_headers)).json()['code'] == 403
    assert (await client.post(f'/api/video/exports/{export.id}/apply', headers=outsider_headers)).json()['code'] == 404
    assert (await client.post(f'/api/video/exports/{export.id}/apply')).json()['code'] == 401
    run.assert_not_awaited()
    assert await AiTask.all().count()==1  # Only the pre-existing shared task; viewer submissions created none.


@pytest.mark.asyncio
async def test_strict_processing_settlement_rolls_back_ledger_and_balance_on_failure(monkeypatch):
    from decimal import Decimal
    from test.test_services.test_video_enhancement_billing import completed_export
    from services.video_enhancement.settlement import settle_enhancement
    from models.usage_record import ModelUsageRecord
    from auth.models import BalanceTransaction
    team=await Team.create(name='settlement-team',balance=10)
    task,export=await completed_export()
    task.request_params={**task.request_params,'team_id':team.id}
    await task.save()
    original=BalanceTransaction.create
    monkeypatch.setattr(BalanceTransaction,'create',AsyncMock(side_effect=RuntimeError('commit failed')))
    with pytest.raises(RuntimeError):await settle_enhancement(task,export)
    await team.refresh_from_db()
    assert team.balance==Decimal('10')
    assert await ModelUsageRecord.all().count()==0
    monkeypatch.setattr(BalanceTransaction,'create',original)
    await settle_enhancement(task,export)
    await settle_enhancement(task,export)
    await team.refresh_from_db()
    assert team.balance==Decimal('9.583333')
    assert await BalanceTransaction.filter(usage_record_id__not_isnull=True).count()==1


@pytest.mark.asyncio
async def test_global_admin_must_select_the_project_team_before_export_admission(client, monkeypatch):
    team = await Team.create(name='admin-export-team', balance=10)
    admin, _ = await _create_member('global-export-admin', team)
    admin.is_super_admin = True
    await admin.save()
    novel = await Novel.create(name='Scoped export', team_id=team.id, created_by=admin.id)
    chapter = await Chapter.create(novel=novel, number=1, name='One', content='Fixture')
    headers = _auth(await _login(client, admin.username))
    response = (await client.post('/api/video/exports', json={'chapter_id':chapter.id}, headers=headers)).json()
    assert response['code'] == 403
    from services.video_enhancement.sources import require_generation_scope
    await require_generation_scope(novel.id, team.id)
    assert await AiTask.all().count() == 0


@pytest.mark.asyncio
async def test_single_video_history_and_preparation_use_existing_project_permissions(client, monkeypatch):
    from models.scene import Scene
    from models.video import Video
    team=await Team.create(name='clip-team',balance=10)
    other=await Team.create(name='other-clip-team',balance=10)
    owner,_=await _create_member('clip-owner',team)
    viewer,_=await _create_member('clip-viewer',team,role='viewer')
    outsider,_=await _create_member('clip-outsider',other)
    novel=await Novel.create(name='Clip source',team_id=team.id,created_by=owner.id)
    chapter=await Chapter.create(novel=novel,number=1,name='One',content='Fixture')
    scene=await Scene.create(chapter=chapter,sequence=1)
    video=await Video.create(scene=scene,model_type=1,status=3,url='/media/clip.mp4')
    await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,team_id=team.id,source_video_id=video.id,
        identity_key='a'*64,source_version='b'*64,source_media_ref='/media/exports/1/source.mp4')
    run=AsyncMock();monkeypatch.setattr('api.video_export.ai_task_executor.run',run)
    viewer_headers=_auth(await _login(client,viewer.username))
    outsider_headers=_auth(await _login(client,outsider.username))
    own=(await client.get(f'/api/video/exports/video/{video.id}',headers=viewer_headers)).json()
    assert own['code']==0 and own['data'][0]['source_video_id']==video.id
    assert (await client.post(f'/api/video/exports/video/{video.id}',headers=viewer_headers)).json()['code']==403
    assert (await client.get(f'/api/video/exports/video/{video.id}',headers=outsider_headers)).json()['code']==404
    assert (await client.post(f'/api/video/exports/video/{video.id}',headers=outsider_headers)).json()['code']==404
    assert (await client.get(f'/api/video/exports?chapter_id={chapter.id}',headers=viewer_headers)).json()['data']==[]
    run.assert_not_awaited()
    assert await AiTask.all().count()==0
