import pytest
from auth.models import Team
from config import settings
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.config import AiModelConfig
from models.ai_task import AiTask
from models.video import Video
from test.test_auth.test_team_scoping import _create_member, _login, _auth

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason='AUTH_ENABLED=true permission suite')


@pytest.mark.asyncio
async def test_project_defaults_and_automatic_generation_keep_team_and_role_boundaries(client):
    team = await Team.create(name='Video defaults', balance=10)
    foreign = await Team.create(name='Other video defaults', balance=10)
    creator, _ = await _create_member('defaults_creator', team)
    viewer, _ = await _create_member('defaults_viewer', team, role='viewer')
    outsider, _ = await _create_member('defaults_outsider', foreign)
    novel = await Novel.create(name='Scoped defaults', team_id=team.id, created_by=creator.id)
    chapter = await Chapter.create(novel=novel, number=1, name='Chapter', content='Story')
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='Keep prompt')
    config = await AiModelConfig.create(task_type=4, name='Video', model='test', api_key='test',
        base_url='https://example.test', api_protocol='volcengine_ark', video_model_type='seedance_2_mini', is_active=True)
    payload = {'chapter_id': chapter.id, 'settings': {'model_config_id': config.id, 'resolution': '480p',
        'aspect_ratio': '16:9', 'return_last_frame': True, 'auto_enhancement': None}, 'remember': True}
    headers = _auth(await _login(client, creator.username))
    assert (await client.post(f'/api/novel/{novel.id}/video-defaults', json=payload, headers=headers)).json()['code'] == 0
    for user, expected in ((viewer, 403), (outsider, 404)):
        token = _auth(await _login(client, user.username))
        assert (await client.post(f'/api/novel/{novel.id}/video-defaults', json=payload, headers=token)).json()['code'] == expected
        assert (await client.post('/api/video/generate/', json={'scene_id': scene.id, 'model_config_id': config.id,
            'auto_enhancement': {'model_config_id': 1, 'resolution': '1080p'}}, headers=token)).json()['code'] == expected
    assert (await client.post(f'/api/novel/{novel.id}/video-defaults', json=payload)).json()['code'] == 401
    await Team.filter(id=team.id).update(balance=0)
    response = await client.post('/api/video/generate/', json={'scene_id': scene.id, 'model_config_id': config.id,
        'auto_enhancement': {'model_config_id': 1, 'resolution': '1080p'}}, headers=headers)
    assert response.json()['code'] == 402
    assert await AiTask.all().count() == 0 and await Video.all().count() == 0
    await scene.refresh_from_db(); assert scene.prompt == 'Keep prompt'


@pytest.mark.asyncio
async def test_runtime_role_revocation_blocks_followup_and_task_snapshot_stays_private(client):
    from services.video_enhancement.automatic import execution_context
    from fastapi import HTTPException
    team = await Team.create(name='Followup role', balance=10)
    viewer, _ = await _create_member('followup_revoked', team, role='viewer')
    with pytest.raises(HTTPException) as error:
        await execution_context({'user_id': viewer.id, 'team_id': team.id})
    assert error.value.status_code == 403
    novel = await Novel.create(name='Private snapshot', team_id=team.id)
    task = await AiTask.create(task_type=4, status=2, request_params={'novel_id': novel.id,
        'auto_enhancement_snapshot': {'pricing': {'private_tier': 123}, 'base_url': 'https://private.example'}})
    response = await client.get(f'/api/task/{task.id}', headers=_auth(await _login(client, viewer.username)))
    assert response.json()['code'] == 0
    assert 'auto_enhancement_snapshot' not in response.json()['data']['request_params']
    assert 'private_tier' not in response.text
