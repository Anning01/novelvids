from datetime import datetime, timezone

import pytest

from auth.models import Team
from config import settings
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.portfolio import PortfolioEpisode, PortfolioWork
from models.usage_record import ModelUsageRecord
from services.schema_compat import ensure_video_editor_schema
from services.video_enhancement.media import export_media
from test.test_auth.test_finished_episodes import completed
from test.test_auth.test_team_scoping import _auth, _create_member, _login
from test.test_services.test_video_editor import ffmpeg

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason='AUTH_ENABLED=true permission suite')


async def account(client, team, username, role):
    user, _ = await _create_member(username, team, role=role)
    return user, _auth(await _login(client, username))


async def test_archive_groups_legacy_exports_and_preserves_profiles_on_restart(client):
    team = await Team.create(name='Portfolio', balance=1)
    producer, creator = await account(client, team, 'portfolio_creator', 'creator')
    _, viewer = await account(client, team, 'portfolio_viewer', 'viewer')
    project = await Novel.create(name='Two episode work', team_id=team.id, created_by=producer.id, project_type='短剧')
    first = await Chapter.create(novel=project, number=1, name='First', content='Internal screenplay')
    second = await Chapter.create(novel=project, number=2, name='Second', content='Internal screenplay')
    older = await completed(first, 1)
    newest = await completed(first, 2)
    second_export = await completed(second, 1)
    created = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    finished = datetime(2026, 10, 3, 11, tzinfo=timezone.utc)
    await Novel.filter(id=project.id).update(created_at=created)
    await AiTask.filter(id=older.task_id).update(finished_at=created)
    await AiTask.filter(id__in=[newest.task_id, second_export.task_id]).update(finished_at=finished)
    admin, admin_headers = await account(client, team, 'portfolio_cost_admin', 'admin')
    other = await Team.create(name='Cost boundary', balance=1)
    for team_id, user_id, cost in [(team.id, producer.id, '6.123456'), (team.id, admin.id, '9.876544'), (other.id, admin.id, '100')]:
        await ModelUsageRecord.create(novel_id=project.id, team_id=team_id, user_id=user_id, cost=cost,
                                      task_type=4, billing_type='video', model='demo')
    path = f'/api/portfolio/{project.id}'
    data = (await client.get('/api/portfolio', headers=viewer)).json()['data']
    assert data['counts'] == {'all': 1, 'pending': 0, 'public': 0, 'private': 1, 'featured': 0}
    assert data['items'][0]['episode_count'] == 2
    assert data['items'][0]['cover_export_id'] == newest.id
    assert data['items'][0]['duration'] == 2
    assert data['items'][0]['producer'] == (producer.nickname or producer.username)
    assert data['items'][0]['production_seconds'] == 2 * 86400 + 3 * 3600
    assert data['items'][0]['recorded_cost'] is None
    team_card = (await client.get('/api/portfolio', headers=admin_headers)).json()['data']['items'][0]
    assert team_card['recorded_cost'] == 16 and team_card['cost_scope'] == 'project'
    own = (await client.get(path, headers=creator)).json()['data']
    assert own['recorded_cost'] == 6.123456 and own['cost_scope'] == 'self'
    assert data['archive_options'] == [{'id': project.id, 'name': project.name}]
    assert (await client.get('/api/portfolio?search=not-found', headers=viewer)).json()['data']['total'] == 0
    profile = {'title': 'Archived name', 'description': 'Synopsis', 'category': '短剧', 'tags': ['悬疑'],
               'revision': 0, 'cover_chapter_id': second.id}
    assert (await client.put(path, headers=viewer, json=profile)).json()['code'] == 403
    saved = (await client.put(path, headers=creator, json=profile)).json()['data']
    assert saved['revision'] == 1
    assert saved['cover_export_id'] != newest.id
    assert (await client.put(path, headers=creator, json=profile)).json()['code'] == 409
    submitted = (await client.put(f'{path}/status', headers=creator, json={'action': 'submit', 'revision': 1})).json()['data']
    assert submitted['status'] == 'pending'
    await ensure_video_editor_schema()
    await ensure_video_editor_schema()
    filtered = (await client.get('/api/portfolio?status=pending&search=Archived', headers=viewer)).json()['data']
    assert filtered['items'][0]['tags'] == ['悬疑']
    assert await PortfolioWork.filter(novel_id=project.id).count() == 1


async def test_public_episodes_are_pinned_reviewed_and_revoked(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path / 'private'))
    team = await Team.create(name='Publishers', balance=1)
    outside_team = await Team.create(name='Outside', balance=1)
    _, admin = await account(client, team, 'portfolio_admin', 'admin')
    _, creator = await account(client, team, 'portfolio_writer', 'creator')
    _, outside = await account(client, outside_team, 'portfolio_outside', 'admin')
    project = await Novel.create(name='Private original', team_id=team.id, content='Secret screenplay')
    first = await Chapter.create(novel=project, number=1, name='First', content='Secret script')
    second = await Chapter.create(novel=project, number=2, name='Second', content='Secret script')
    old = await completed(first, 1)
    new = await completed(first, 2)
    hidden = await completed(second, 1)
    source = tmp_path / 'video.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'color=blue:s=160x90:r=24:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', source)
    await export_media.store(old.media_ref, source)
    private = f'/api/portfolio/{project.id}'
    public = f'/api/portfolio/public/{project.id}'
    action = f'{private}/status'
    legacy = f'/api/finished-episodes/chapters/{second.id}/publication'
    assert (await client.put(legacy, headers=admin, json={'export_id': hidden.id})).json()['code'] == 0
    assert (await client.get(public)).json()['code'] == 404
    assert (await client.get(private, headers=outside)).json()['code'] == 404
    assert (await client.put(action, headers=creator, json={'action': 'publish', 'revision': 0, 'export_ids': [old.id]})).json()['code'] == 403
    assert (await client.put(action, headers=admin, json={'action': 'recommend', 'revision': 0, 'featured': True})).json()['code'] == 409
    assert (await client.put(action, headers=admin, json={'action': 'publish', 'revision': 0, 'export_ids': [old.id, new.id]})).json()['code'] == 422
    assert not await PortfolioWork.filter(novel_id=project.id).exists()
    published = (await client.put(action, headers=admin, json={'action': 'publish', 'revision': 0, 'export_ids': [old.id]})).json()['data']
    assert published['status'] == 'public' and not published['featured']
    assert published['episode_count'] == 2
    guest = (await client.get(public)).json()['data']
    assert [episode['version']['id'] for episode in guest['episodes']] == [old.id]
    assert 'Secret' not in str(guest) and guest['producer_id'] is None
    assert guest['cover_export_id'] == old.id
    assert {'production_seconds', 'recorded_cost', 'cost_scope'}.isdisjoint(guest)
    assert (await client.get(f'{public}/episodes/{hidden.id}/video')).json()['code'] == 404
    assert (await client.get(f'/api/finished-episodes/versions/{hidden.id}/video', headers=outside)).json()['code'] == 404
    media = f'{public}/episodes/{old.id}'
    assert (await client.get(f'{media}/cover')).headers['content-type'] == 'image/jpeg'
    response = await client.get(f'{media}/video', headers={'Range': 'bytes=0-15'})
    assert response.status_code == 206 and len(response.content) == 16
    assert response.headers['cache-control'] == 'private, no-store'
    recommended = (await client.put(action, headers=admin, json={'action': 'recommend', 'revision': 1, 'featured': True, 'featured_order': 4})).json()['data']
    assert recommended['featured'] and recommended['featured_order'] == 4
    withdrawn = (await client.put(action, headers=admin, json={'action': 'withdraw', 'revision': 2})).json()['data']
    assert withdrawn['status'] == 'withdrawn' and not withdrawn['featured']
    assert (await client.get(public)).json()['code'] == 404
    assert (await client.get(f'{media}/cover')).json()['code'] == 404
    revoked = await client.get(f'{media}/video')
    assert revoked.status_code == 404 and revoked.json()['code'] == 404
    assert revoked.headers['cache-control'] == 'private, no-store'
    assert await PortfolioEpisode.filter(export_id=old.id).exists()


async def test_public_object_storage_streams_range_without_exposing_upstream(client, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import httpx

    class VideoBytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'test'

    calls = []

    @asynccontextmanager
    async def open_download(key, *, byte_range):
        calls.append((key, byte_range))
        if byte_range == 'bytes=100-':
            yield httpx.Response(416, headers={'Content-Range': 'bytes */20'}, stream=VideoBytes())
        else:
            yield httpx.Response(206, headers={'Content-Range': 'bytes 0-3/20', 'Content-Length': '4',
                                              'X-OSS-Request-ID': 'private'}, stream=VideoBytes())

    monkeypatch.setattr('api.portfolio.oss', SimpleNamespace(enabled=True, open_download=open_download))
    project = await Novel.create(name='Cloud work')
    chapter = await Chapter.create(novel=project, number=1, name='First', content='')
    export = await completed(chapter, 1, ref='uploads/1/exports/1/edited.mp4')
    work = await PortfolioWork.create(novel=project, title=project.name, status='public')
    await PortfolioEpisode.create(work=work, chapter=chapter, export=export)
    path = f'/api/portfolio/public/{project.id}/episodes/{export.id}/video'
    response = await client.get(path, headers={'Range': 'bytes=0-3'})
    assert calls == [(export.media_ref, 'bytes=0-3')]
    assert response.status_code == 206 and response.content == b'test'
    assert response.headers['content-range'] == 'bytes 0-3/20'
    assert 'x-oss-request-id' not in response.headers
    response = await client.get(path, headers={'Range': 'bytes=100-'})
    assert response.status_code == 416 and response.content == b''
    assert response.headers['content-range'] == 'bytes */20'

@pytest.mark.parametrize('style_key,custom_prompt,project_type,expected', [
    ('xianxia-3d', None, None, None),
    ('realistic-general', None, '悬疑', None),
    (None, 'Private custom prompt', None, '自定义风格'),
    ('auto', None, None, 'AI 识别风格'),
    (None, None, '历史悬疑', '历史悬疑'),
    (None, None, None, '其他'),
])
async def test_work_type_follows_creation_settings_without_manual_selection(
    client, style_key, custom_prompt, project_type, expected,
):
    from prompts.styles import get_style
    if expected is None:
        expected = get_style(style_key).label
    team = await Team.create(name='Automatic type team', balance=1)
    producer, creator = await account(client, team, 'portfolio_auto_type', 'creator')
    project = await Novel.create(
        name='Automatic work', team_id=team.id, created_by=producer.id, project_type=project_type,
        style_key=style_key, custom_style_prompt=custom_prompt,
    )
    chapter = await Chapter.create(novel=project, number=1, name='First', content='')
    await completed(chapter, 1)
    archive = await PortfolioWork.create(novel=project, title=project.name, category='其他')
    path = f'/api/portfolio/{project.id}'
    item = (await client.get(path, headers=creator)).json()['data']
    assert item['category'] == expected
    assert 'category_options' not in item
    assert 'Private custom prompt' not in str(item)
    listed = (await client.get('/api/portfolio', headers=creator)).json()['data']['items'][0]
    assert listed['category'] == expected
    saved = await client.put(path, headers=creator, json={'title': project.name, 'revision': 1, 'category': '任意手写类型'})
    assert saved.json()['data']['category'] == expected
    await archive.refresh_from_db()
    assert archive.category == expected
