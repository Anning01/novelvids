"""Explicit acceptance: run with a fresh NOVELVIDS_TEST_POSTGRES_URL and AUTH_ENABLED=true."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
import shutil
import sys
from urllib.parse import urlsplit

from tortoise import Tortoise

from auth.models import Team, TeamMember, User, UserSession
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from test.test_auth import issue_test_session
from test.test_services.test_remake_sync_contract import remake_package  # noqa: F401


@asynccontextmanager
async def connection(root, media):
    database = os.environ['NOVELVIDS_TEST_POSTGRES_URL']
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'services.local_mcp.server', '--allow-root', str(root),
        '--app-url', 'https://studio.example',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, 'DATABASE_URL': database, 'AUTH_ENABLED': 'true', 'MEDIA_PATH': str(media)},
    )

    async def rpc(method, params):
        process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}) + '\n').encode())
        await process.stdin.drain()
        line = await asyncio.wait_for(process.stdout.readline(), 30)
        assert line, (await process.stderr.read()).decode()
        result = json.loads(line)
        assert 'error' not in result, result
        return result['result']

    async def call(name, arguments):
        result = await rpc('tools/call', {'name': name, 'arguments': arguments})
        return result['isError'], json.loads(result['content'][0]['text'])

    try:
        await rpc('initialize', {'protocolVersion': '2025-11-25'})
        yield call
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def test_authenticated_postgres_real_process_concurrency_restart_and_revocation(client, tmp_path, remake_package):
    assert Tortoise.get_connection('default').capabilities.dialect == 'postgres'
    user = await User.create(username='postgres-mcp-author', password_hash='!')
    team = await Team.create(name='PostgreSQL MCP acceptance')
    await TeamMember.create(user=user, team=team, role='creator')
    token = await issue_test_session(user.username)
    headers = {'Authorization': 'Bearer ' + token, 'X-Team-Id': str(team.id)}
    read = {'work_id': 'remake-work', 'episode_id': 'ep1', 'shot_id': 'shot4'}

    async def approve(call):
        error, response = await call('read_episode', read)
        assert error and response['status'] == 'authorization_required'
        code = urlsplit(response['url']).fragment.rsplit('/', 1)[1]
        approved = await client.post(f'/api/auth/local-mcp/{code}/approve', headers=headers)
        assert approved.json()['code'] == 0

    arguments = {'directory': str(remake_package), 'request_id': 'pg-remake', 'confirmed': True}
    async with connection(tmp_path, tmp_path / 'media') as first, connection(tmp_path, tmp_path / 'media') as second:
        await approve(first)
        await approve(second)
        responses = await asyncio.gather(first('import_episode', arguments), second('import_episode', arguments))
        assert responses[0] == responses[1] and not responses[0][0], responses
        receipt = responses[0][1]
        assert await Novel.filter(team_id=team.id).count() == 1
        assert await Chapter.all().count() == await RemakeSource.all().count() == 1
        assert not await AiTask.all().exists()
        assert receipt['workflow_kind'] == 'remake'
        row = receipt['shots'][0]
        base = {**read, 'directory': str(remake_package), 'confirmed': True, 'base_version': row['version']}
        results = await asyncio.gather(
            first('update_shot', {**base, 'request_id': 'pg-update-a', 'changes': {'prompt': 'process A'}}),
            second('update_shot', {**base, 'request_id': 'pg-update-b', 'changes': {'prompt': 'process B'}}),
        )
        assert sorted(error for error, _ in results) == [False, True], results
        failure = next(value for error, value in results if error)
        assert failure['reason'] == 'version_conflict'
        current = await Scene.get(id=row['local_id'])
        assert current.prompt in {'process A', 'process B'}
        source = await RemakeSource.get(chapter_id=receipt['chapter_id'])
        assert source.team_id == team.id and source.created_by == user.id
        assert (tmp_path / 'media' / source.object_key).read_bytes() == (remake_package / 'source.mp4').read_bytes()

        # Distinct request IDs must also serialize first creation of one shared work.
        packages = []
        for number in (1, 2):
            directory = tmp_path / f'parallel-{number}'
            shutil.copytree(remake_package, directory)
            manifest = json.loads((directory / 'episode.json').read_text())
            manifest.update(work={'id': 'parallel-work', 'name': '并发分集'},
                            episode={'id': f'ep{number}', 'name': f'第{number}集'}, number=number)
            (directory / 'episode.json').write_text(json.dumps(manifest))
            packages.append({'directory': str(directory), 'request_id': f'parallel-{number}', 'confirmed': True})
        parallel = await asyncio.gather(first('import_episode', packages[0]), second('import_episode', packages[1]))
        assert all(not error for error, _ in parallel), parallel
        assert parallel[0][1]['novel_id'] == parallel[1][1]['novel_id']
        assert await RemakeSource.filter(novel_id=parallel[0][1]['novel_id']).count() == 2

    # Repeated safe schema initialization and process restart preserve all imported records.
    await Tortoise.generate_schemas(safe=True)
    async with connection(tmp_path, tmp_path / 'media') as restarted:
        await approve(restarted)
        error, replayed = await restarted('import_episode', arguments)
        assert not error and replayed == receipt
        error, reread = await restarted('read_episode', read)
        assert not error and reread['shots'][0]['prompt'] == current.prompt
        await UserSession.filter(user=user).delete()
        error, revoked = await restarted('read_episode', read)
        assert error and revoked['status'] == 'authorization_required'
