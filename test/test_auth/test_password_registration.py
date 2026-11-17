"""Public password signup creates an ordinary account with an isolated workspace."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from auth.models import Team, TeamMember, User, UserSession
from auth.schemas import RegisterIn
from auth.security import hash_token, verify_password
from auth.service import auth_service
from config import settings
from services.invites import create_invite

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not settings.AUTH_ENABLED, reason='requires auth')]


@pytest.fixture(autouse=True)
def password_signup(monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_PROVIDER', 'password')
    monkeypatch.setattr(settings, 'PASSWORD_SIGNUP_ENABLED', True, raising=False)


async def test_public_signup_creates_an_ordinary_user_and_own_team(client):
    unrelated = await Team.create(name='Existing team')
    response = await client.post('/api/auth/register', json={
        'username': ' new-creator ', 'nickname': '小影', 'password': 'a-long-password',
    })
    payload = response.json()
    assert payload['code'] == 0, payload
    user = await User.get(username='new-creator')
    assert not user.is_super_admin and user.nickname == '小影'
    assert verify_password('a-long-password', user.password_hash)
    assert 'password_hash' not in payload['data']['user']
    team = await Team.get(owner_user_id=user.id)
    assert team.balance == 0
    assert await TeamMember.filter(user=user).count() == 1
    assert not await TeamMember.filter(user=user, team=unrelated).exists()
    token = payload['data']['token']
    assert await UserSession.filter(user=user, token_hash=hash_token(token)).exists()
    headers = {'Authorization': f'Bearer {token}'}
    me = (await client.get('/api/auth/me', headers=headers)).json()
    assert me['data']['is_super_admin'] is False
    assert me['data']['memberships'][0]['team_id'] == team.id
    assert (await client.get('/api/users', headers=headers)).json()['code'] == 403
    assert (await client.post('/api/auth/login', json={
        'username': 'new-creator', 'password': 'a-long-password',
    })).json()['code'] == 0


@pytest.mark.parametrize('extra', [{'is_super_admin': True}, {'role': 'admin'}, {'status': 1}])
async def test_public_signup_rejects_privilege_fields(client, extra):
    response = await client.post('/api/auth/register', json={
        'username': 'ordinary', 'password': 'a-long-password', **extra,
    })
    assert response.json()['code'] == 422
    assert not await User.filter(username='ordinary').exists()


@pytest.mark.parametrize('changes', [{'username': '   '}, {'password': 'short'}, {'invite_token': ''}])
async def test_signup_validates_credentials_before_creating_data(client, changes):
    response = await client.post('/api/auth/register', json={
        'username': 'ordinary', 'password': 'a-long-password', **changes,
    })
    assert response.json()['code'] == 422
    assert not await User.all().exists()


async def test_duplicate_signup_is_atomic_and_does_not_create_more_teams(client):
    body = {'username': 'same-name', 'password': 'a-long-password'}
    replies = await asyncio.gather(*(client.post('/api/auth/register', json=body) for _ in range(2)))
    assert sorted(reply.json()['code'] for reply in replies) == [0, 400]
    assert await User.filter(username='same-name').count() == 1
    assert await Team.all().count() == 1
    assert await TeamMember.all().count() == 1
    assert await UserSession.all().count() == 1


async def test_failed_workspace_creation_rolls_back_user_and_session(monkeypatch):
    monkeypatch.setattr('services.team_provisioning.create_owned_team', AsyncMock(side_effect=RuntimeError('workspace unavailable')))
    with pytest.raises(RuntimeError, match='workspace unavailable'):
        await auth_service.register(RegisterIn(username='rollback', password='a-long-password'))
    assert not await User.filter(username='rollback').exists()
    assert not await UserSession.all().exists()


async def test_signup_switch_does_not_disable_existing_invitation_registration(client, monkeypatch):
    monkeypatch.setattr(settings, 'PASSWORD_SIGNUP_ENABLED', False)
    status = (await client.get('/api/auth/status')).json()['data']
    assert status['registration_enabled'] is False
    body = {'username': 'invited', 'password': 'a-long-password'}
    assert (await client.post('/api/auth/register', json=body)).json()['code'] == 403
    team = await Team.create(name='Inviting team')
    invite = await create_invite(team.id, 'creator')
    reply = (await client.post('/api/auth/register', json={**body, 'invite_token': invite.token})).json()
    assert reply['code'] == 0, reply
    user = await User.get(username='invited')
    assert not user.is_super_admin
    assert (await TeamMember.get(user=user, team=team)).role == 'creator'


async def test_qiling_provider_never_exposes_password_signup(client, monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_PROVIDER', 'qiling')
    assert (await client.get('/api/auth/status')).json()['data']['registration_enabled'] is False
    response = await client.post('/api/auth/register', json={'username': 'ordinary', 'password': 'a-long-password'})
    assert response.json()['code'] == 404
    assert not await User.all().exists()


async def test_status_reports_password_registration_available(client):
    assert (await client.get('/api/auth/status')).json()['data']['registration_enabled'] is True


async def test_invalid_invite_never_falls_back_to_public_signup(client):
    response = await client.post('/api/auth/register', json={
        'username': 'bad-invite', 'password': 'a-long-password', 'invite_token': 'missing',
    })
    assert response.json()['code'] == 404
    assert not await User.all().exists()


async def test_public_signup_uses_existing_ip_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, 'LOGIN_RATE_LIMIT_ENABLED', True)
    monkeypatch.setattr(settings, 'LOGIN_RATE_LIMIT_IP_ATTEMPTS', 2)
    for number in range(2):
        assert (await client.post('/api/auth/register', json={
            'username': f'limited-{number}', 'password': 'a-long-password',
        })).json()['code'] == 0
    response = await client.post('/api/auth/register', json={
        'username': 'limited-third', 'password': 'a-long-password',
    })
    assert response.status_code == 429
    assert int(response.headers['Retry-After']) > 0
    assert not await User.filter(username='limited-third').exists()
