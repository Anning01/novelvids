import pytest
from httpx import ASGITransport, AsyncClient
from archive_app import app,current_principal,Principal
from auth.models import Team,TeamMember,User
from models.novel import Novel
from models.chapter import Chapter


@pytest.mark.asyncio
async def test_legacy_projects_are_scoped_and_read_only():
    owner=await User.create(username='owner')
    other=await User.create(username='other')
    team=await Team.create(name='Historical',owner_user_id=owner.id)
    await TeamMember.create(team=team,user=owner,role='creator')
    project=await Novel.create(name='Paid work',team_id=team.id)
    await Chapter.create(novel=project,number=1,name='Episode',content='Original',screenplay='Script')
    user=Principal(id=owner.id)
    app.dependency_overrides[current_principal]=lambda:user
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            result=(await client.get('/api/legacy-works/projects')).json()['data']
            assert [item['id'] for item in result['items']]==[project.id]
            assert result['automatic_deletion'] is False
            plan=(await client.get(f'/api/legacy-works/projects/{project.id}/transfer')).json()['data']
            assert plan['project']['chapters'][0]['screenplay']=='Script'
            assert 'team_id' not in plan['project']['novel']
            assert (await client.delete(f'/api/legacy-works/projects/{project.id}')).status_code==404
            user=Principal(id=other.id)
            assert not (await client.get('/api/legacy-works/projects')).json()['data']['items']
            assert (await client.get(f'/api/legacy-works/projects/{project.id}/transfer')).json()['code']==404
    finally:app.dependency_overrides.clear()
