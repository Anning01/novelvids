import cv2
import numpy as np
import pytest
from unittest.mock import AsyncMock

from auth.models import User
from config import settings
from services.user_profile import MAX_AVATAR_BYTES
from test.test_auth import issue_test_session

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not settings.AUTH_ENABLED, reason='AUTH_ENABLED=true required')]


async def account():
    user = await User.create(username='profile-owner', nickname='原昵称', avatar_url='/media/old.png')
    token = await issue_test_session(user.username)
    return user, {'Authorization': 'Bearer ' + token}


async def test_profile_updates_only_authenticated_users_own_display_name(client, monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_PROVIDER', 'qiling')
    user, headers = await account()
    other = await User.create(username='profile-other', nickname='不更改')
    response = await client.patch('/api/auth/profile', json={'nickname':'  小新✨  '}, headers=headers)
    assert response.json()['code'] == 0
    assert response.json()['data']['nickname'] == '小新✨'
    assert (await client.get('/api/auth/me',headers=headers)).json()['data']['user']['nickname'] == '小新✨'
    for extra in ({'user_id':other.id}, {'is_super_admin':True}, {'username':'changed'}, {'avatar_url':'javascript:alert(1)'}):
        response = await client.patch('/api/auth/profile', json={'nickname':'越权',**extra}, headers=headers)
        assert response.json()['code'] == 422
    await user.refresh_from_db()
    await other.refresh_from_db()
    assert user.nickname == '小新✨' and not user.is_super_admin and user.username == 'profile-owner'
    assert other.nickname == '不更改'


@pytest.mark.parametrize('nickname', ['', '   ', 'x'*101])
async def test_invalid_nickname_keeps_saved_profile(client, nickname):
    user, headers = await account()
    response = await client.patch('/api/auth/profile', json={'nickname':nickname}, headers=headers)
    assert response.json()['code'] == 422
    await user.refresh_from_db()
    assert user.nickname == '原昵称'


async def test_profile_endpoints_require_login(client):
    response = await client.patch('/api/auth/profile',json={'nickname':'new'})
    assert response.json()['code'] == 401
    response = await client.post('/api/auth/avatar',files={'file':('a.png',b'fake','image/png')})
    assert response.json()['code'] == 401


@pytest.mark.parametrize('extension,mime', [('.png','image/png'),('.jpg','image/jpeg'),('.webp','image/webp')])
async def test_avatar_validates_real_image_and_saves_to_oss_without_changing_other_accounts(client, monkeypatch, extension, mime):
    import services.user_profile as profile
    user, headers = await account()
    other = await User.create(username='other-avatar',avatar_url='/media/other.png')
    _, encoded = cv2.imencode(extension,np.full((128,128,3),120,dtype=np.uint8))
    data = encoded.tobytes()
    provider = type('Provider',(),{'enabled':True,'put_bytes':AsyncMock()})()
    monkeypatch.setattr(profile,'oss',provider)
    monkeypatch.setattr('services.oss.resolve_media_url',lambda value:'https://media.example/'+value if value.startswith('uploads/') else value)
    response = await client.post('/api/auth/avatar',headers=headers,
        data={'user_id':str(other.id)},files={'file':('../../unsafe.html',data,'text/html')})
    assert response.json()['code'] == 0
    assert response.json()['data']['avatar_url'].startswith('https://media.example/uploads/')
    await user.refresh_from_db()
    assert user.avatar_url.startswith('uploads/') and user.avatar_url.endswith(extension)
    assert provider.put_bytes.call_args.args == (user.avatar_url,data,mime)
    await other.refresh_from_db()
    assert other.avatar_url == '/media/other.png'


@pytest.mark.parametrize('content', [b'<svg onload="alert(1)"></svg>',b'not-an-image',b'x'*(MAX_AVATAR_BYTES+1)])
async def test_avatar_rejects_unsupported_or_oversized_content_without_replacing_avatar(client, content):
    user, headers = await account()
    response = await client.post('/api/auth/avatar',headers=headers,files={'file':('fake.png',content,'image/png')})
    assert response.json()['code'] in {400,422}
    await user.refresh_from_db()
    assert user.avatar_url == '/media/old.png'
