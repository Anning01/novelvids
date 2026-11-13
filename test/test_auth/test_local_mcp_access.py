import json
from urllib.parse import urlsplit
from uuid import UUID
import pytest
from auth.models import Team, TeamMember, User, UserSession
from config import settings
from models.novel import Novel
from services.local_mcp.access import LocalMcpAccess
from services.local_mcp.server import MCPServer
from services.local_mcp.sync import WorkSync
from test.test_auth import issue_test_session
from test.test_services.test_local_mcp import package

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated routes")


async def test_browser_session_binds_roles_team_replay_and_revocation(client, tmp_path):
    async def tool(server, name, arguments):
        r = await server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':arguments}})
        return json.loads(r['result']['content'][0]['text'])

    async def start():
        s = MCPServer(WorkSync(tmp_path,tmp_path/'media'), LocalMcpAccess('http://localhost:3000'))
        await s.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
        auth = await tool(s, 'read_episode', {'work_id':'one-book','episode_id':'ep1'})
        assert auth['status'] == 'authorization_required'
        return s, '/api/auth/local-mcp/'+str(UUID(urlsplit(auth['url']).fragment.split('/')[-1]))+'/approve'

    author = await User.create(username='mcp-writer', password_hash='!')
    outsider = await User.create(username='mcp-outsider', password_hash='!')
    a = await Team.create(name='mcp-A')
    b = await Team.create(name='mcp-B')
    member = await TeamMember.create(user=author,team=a,role='creator')
    await TeamMember.create(user=outsider,team=b,role='admin')
    token = await issue_test_session(author.username)
    h = {'Authorization':'Bearer '+token,'X-Team-Id':str(a.id)}
    first, url = await start()
    assert (await client.post(url)).json()['code'] == 401
    assert (await client.post(url, headers={'Authorization': 'Bearer '+token})).json()['code'] == 403
    assert (await client.post(url, headers={**h,'X-Team-Id':str(b.id)})).json()['code'] == 403
    assert (await client.post(url, headers=h)).json()['code'] == 0
    assert (await client.post(url, headers=h)).json()['code'] == 409
    root=package(tmp_path/'book', 'one-book')
    args={'directory':str(root),'request_id':'same-request','confirmed':True}
    receipt=await tool(first,'import_episode',args)
    assert receipt['status']=='ok' and receipt['work_id']=='one-book',receipt
    assert await Novel.filter(id=receipt['novel_id'],team_id=a.id,created_by=author.id).exists()
    assert await tool(first,'import_episode',args)==receipt
    other, url2=await start()
    token2=await issue_test_session(outsider.username)
    assert (await client.post(url2,headers={'Authorization':'Bearer '+token2,'X-Team-Id':str(b.id)})).json()['code']==0
    assert (await tool(other,'read_episode',{'work_id':'one-book','episode_id':'ep1'}))['status']=='rejected'
    second=await tool(other,'import_episode',args)
    assert second['status']=='ok' and second['novel_id']!=receipt['novel_id']
    member.role='viewer'
    await member.save()
    assert (await tool(first,'import_episode',args))['code']==403
    assert (await tool(first,'read_episode',{'work_id':'one-book','episode_id':'ep1'}))['status']=='ok'
    a.status=0
    await a.save(update_fields=['status'])
    assert (await tool(first,'read_episode',{'work_id':'one-book','episode_id':'ep1'}))['code']==403
    a.status=1
    await a.save(update_fields=['status'])
    await UserSession.filter(user=author).delete()
    assert (await tool(first,'read_episode',{'work_id':'one-book','episode_id':'ep1'}))['status']=='authorization_required'
