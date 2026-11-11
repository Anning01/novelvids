import json
from pathlib import Path
import pytest
from models.chapter import Chapter
from models.scene import Scene
from models.video import Video
from schemas.work_package import ImportEpisode, ReadEpisode, UpdateShot
from services.creation_objects import CreationObjects, project_write
from services.local_mcp.package import PackageFiles
from services.local_mcp.server import MCPServer
from services.local_mcp.sync import SyncConflict, WorkSync


def package(root: Path, work='mcp-test'):
    root.mkdir()
    (root / 'episode.json').write_text(json.dumps({'format_version': 1, 'work': {'id': work, 'name': '示例'},
        'episode': {'id': 'ep1', 'name': '第一集'}, 'number': 1}))
    (root / 'screenplay.md').write_text('# 原剧本\n\n原样保留。')
    (root / 'assets.json').write_text('{"assets":[]}')
    shot = {'id': 'shot4', 'name': '第四镜', 'scene_id': 'scene1', 'description': '原描述', 'duration': 14,
            'prompt': '原提示词', 'drafts': {'八栏': '|原文|'}, 'media': [{'path': 'clip.mp4', 'role': 'video'}]}
    (root / 'clip.mp4').write_bytes(b'test media')
    (root / 'storyboard.json').write_text(json.dumps({'scenes': [{'id': 'scene1', 'name': '内景'}], 'shots': [shot]}))
    return root


async def test_import_update_retry_order_and_conflict(tmp_path):
    root = package(tmp_path / 'pack')
    service = WorkSync(tmp_path, tmp_path / 'archive')
    request = ImportEpisode(directory=str(root), request_id='import-test', confirmed=True)
    receipt = await service.import_episode(request)
    assert receipt == await service.import_episode(request)
    assert await Chapter.filter(id=receipt['chapter_id']).count() == 1
    assert (root / 'sync-receipt.json').exists()
    from models.novel import Novel
    assert (await Novel.get(id=receipt['novel_id'])).author == 'Agent 创建'
    assert receipt['location']['path'] == f"/#/create/short-drama/storyboard/{receipt['novel_id']}?chapter={receipt['chapter_id']}"
    assert receipt['location']['url'] == 'http://localhost:3000' + receipt['location']['path']
    url = receipt['archive']['clip.mp4']
    assert (tmp_path / 'archive' / 'work-packages' / url.rsplit('/', 1)[1]).read_bytes() == b'test media'
    shot = receipt['shots'][0]
    target = await Scene.get(id=shot['local_id'])
    video = await Video.create(scene_id=target.id, model_type=1, status=3, url='/media/old.mp4')
    objects = CreationObjects(receipt['novel_id'])
    async with project_write(receipt['novel_id']):
        inserted = await objects.create_scene(target.chapter_id, after_id=0, values={'description': '新插入'})
    request2 = UpdateShot(directory=str(root), request_id='update-test', confirmed=True,
        work_id='mcp-test', episode_id='ep1', shot_id='shot4', base_version=shot['version'], changes={'description': '新描述'})
    updated = await service.update_shot(request2)
    assert updated['shots'][0]['sequence'] == 2
    assert updated == await service.update_shot(request2)
    await inserted.refresh_from_db()
    assert inserted.description == '新插入'
    await video.refresh_from_db()
    assert video.url == '/media/old.mp4'
    await Scene.filter(id=target.id).update(prompt='猫影手改')
    stale = request2.model_copy(update={'request_id': 'stale'})
    with pytest.raises(SyncConflict, match='version_conflict'):
        await service.update_shot(stale)
    await target.refresh_from_db()
    assert target.prompt == '猫影手改'
    changed_retry = request2.model_copy(update={'changes': {'prompt': '不能改'}})
    with pytest.raises(SyncConflict, match='request_id_reused'):
        await service.update_shot(changed_retry)
    with pytest.raises(SyncConflict, match='episode_exists'):
        await service.import_episode(request.model_copy(update={'request_id': 'different-import'}))
    # Archive remains usable after moving away every source file.
    root.rename(tmp_path / 'moved')
    assert (tmp_path / 'archive' / 'work-packages' / url.rsplit('/', 1)[1]).exists()
    assert (await service.read_episode(ReadEpisode(work_id='mcp-test', episode_id='ep1', shot_id='shot4')))['shots'][0]['prompt'] == '猫影手改'


def test_paths_and_reference_validation(tmp_path):
    root = package(tmp_path / 'unsafe', 'unsafe')
    files = PackageFiles(str(root), tmp_path)
    for path in ('../outside', '/etc/passwd'):
        with pytest.raises(ValueError):
            files.read(path)
    (root / 'escape').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        files.read('escape')
    data = json.loads((root / 'storyboard.json').read_text())
    data['shots'][0]['voices'] = [{'asset_id': 'missing', 'mode': 'offscreen', 'text': '喊声', 'start': 0, 'end': 1}]
    (root / 'storyboard.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='声音资产'):
        files.episode()


async def test_mcp_protocol(tmp_path):
    server = MCPServer(WorkSync(tmp_path, tmp_path / 'media'))
    assert 'error' in await server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    initialized = await server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}})
    assert initialized['result']['capabilities']['tools']
    assert await server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None
    listed = await server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'})
    assert len(listed['result']['tools']) == 3
    bad = await server.handle({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'import_episode', 'arguments': {'confirmed': False}}})
    assert bad['result']['isError']


async def test_real_stdio_client_restart_and_schema_safe(tmp_path):
    """An actual pipe client, independent database, and a restarted MCP server."""
    import asyncio
    import os
    import sys
    root = package(tmp_path / 'stdio', 'stdio-work')
    environment = {**os.environ, 'DATABASE_URL': f'sqlite://{tmp_path}/stdio.db',
                   'MEDIA_PATH': str(tmp_path / 'media'), 'AUTH_ENABLED': 'false'}

    async def start():
        return await asyncio.create_subprocess_exec(sys.executable, '-m', 'services.local_mcp.server',
            '--allow-root', str(tmp_path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=environment)

    async def rpc(process, method, params):
        process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}) + '\n').encode())
        await process.stdin.drain()
        line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
        assert line, (await process.stderr.read()).decode()
        return json.loads(line)['result']

    process = await start()
    try:
        assert (await rpc(process, 'initialize', {'protocolVersion': '2025-03-26'}))['protocolVersion'] == '2025-03-26'
        listed = await rpc(process, 'tools/list', {})
        assert {t['name'] for t in listed['tools']} == {'import_episode', 'update_shot', 'read_episode'}
        arguments = {'directory': str(root), 'request_id': 'stdio-import', 'confirmed': True}
        first = await rpc(process, 'tools/call', {'name': 'import_episode', 'arguments': arguments})
        assert not first['isError'], first
    finally:
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 10)
    process = await start()
    try:
        await rpc(process, 'initialize', {})
        retried = await rpc(process, 'tools/call', {'name': 'import_episode', 'arguments': arguments})
        assert retried == first
        data = json.loads(first['content'][0]['text'])
        shot = data['shots'][0]
        changed = await rpc(process, 'tools/call', {'name': 'update_shot', 'arguments': {
            'directory': str(root), 'request_id': 'stdio-shot', 'confirmed': True,
            'work_id': 'stdio-work', 'episode_id': 'ep1', 'shot_id': 'shot4',
            'base_version': shot['version'], 'changes': {'prompt': '通过真实管道更新'}}})
        assert not changed['isError'], changed
        read = await rpc(process, 'tools/call', {'name': 'read_episode', 'arguments': {
            'work_id': 'stdio-work', 'episode_id': 'ep1', 'shot_id': 'shot4'}})
        assert json.loads(read['content'][0]['text'])['shots'][0]['prompt'] == '通过真实管道更新'
    finally:
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 10)


async def test_import_invalid_assets_rolls_back(tmp_path):
    from models.novel import Novel
    from models.work_sync import WorkSyncObject
    count_before = await Novel.all().count()
    root = package(tmp_path / 'invalid', 'invalid-work')
    (root / 'assets.json').write_text(json.dumps({'assets': [
        {'id': 'a', 'name': '资产', 'kind': 'person', 'prompt': '不符合资产协议'}]}))
    with pytest.raises(ValueError):
        await WorkSync(tmp_path, tmp_path / 'media').import_episode(ImportEpisode(
            directory=str(root), request_id='invalid-import', confirmed=True))
    assert not await WorkSyncObject.filter(work_id='invalid-work').exists()
    assert await Novel.all().count() == count_before


async def test_assets_variants_voices_and_other_episodes(tmp_path):
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from prompts.creation_standards import render_asset_design
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    fields = json.loads(snapshot.read('asset_contract'))['zh']['person']['fields']
    prompt = render_asset_design('', {field: '具体的古代粗布视觉设定' for field in fields}, 'person', snapshot, 'zh', '16:9')
    root = package(tmp_path / 'rich', 'rich-work')
    assets = [{'id': 'boy', 'name': '少年', 'kind': 'person', 'prompt': prompt,
               'variants': [{'id': 'winter', 'name': '冬装', 'prompt': prompt}]},
              {'id': 'woman', 'name': '妇人', 'kind': 'person', 'prompt': prompt}]
    (root / 'assets.json').write_text(json.dumps({'assets': assets}))
    board = json.loads((root / 'storyboard.json').read_text())
    board['shots'][0]['visual'] = [{'asset_id': 'boy', 'variant_id': 'winter'}]
    board['shots'][0]['voices'] = [
        {'asset_id': 'woman', 'mode': 'offscreen', 'text': '开饭了', 'start': 1, 'end': 3},
        {'asset_id': 'boy', 'mode': 'os', 'text': '心声', 'start': 4, 'end': 6}]
    (root / 'storyboard.json').write_text(json.dumps(board))
    service = WorkSync(tmp_path, tmp_path / 'media')
    first = await service.import_episode(ImportEpisode(directory=str(root), request_id='rich-import', confirmed=True))
    target = await Scene.get(id=first['shots'][0]['local_id'])
    assert await target.assets.all().values_list('canonical_name', flat=True) == ['少年']
    variant = await AssetVariant.get(name='冬装', asset__novel_id=first['novel_id'])
    assert target.metadata['asset_variant_ids'] == {str(variant.asset_id): variant.id}
    assert variant.chapter_numbers == [1]
    assert all(a.source_chapters == [1] and a.last_updated_chapter == 1 for a in await Asset.filter(novel_id=first['novel_id']))
    # Same shared asset IDs in another episode reuse objects rather than duplicating them.
    manifest = json.loads((root / 'episode.json').read_text())
    manifest.update(episode={'id': 'ep2', 'name': '第二集'}, number=2)
    (root / 'episode.json').write_text(json.dumps(manifest))
    second = await service.import_episode(ImportEpisode(directory=str(root), request_id='rich-second', confirmed=True))
    assert second['novel_id'] == first['novel_id'] and second['chapter_id'] != first['chapter_id']
    assert await Asset.filter(novel_id=first['novel_id']).count() == 2
    assert await Chapter.filter(novel_id=first['novel_id']).count() == 2
    assert all(a.source_chapters == [1, 2] and a.last_updated_chapter == 2 for a in await Asset.filter(novel_id=first['novel_id']))
    await variant.refresh_from_db()
    assert variant.chapter_numbers == [1, 2]
    # Mixing base and a form in a third episode must not install a form as its default.
    manifest.update(episode={'id': 'ep3', 'name': '第三集'}, number=3)
    (root / 'episode.json').write_text(json.dumps(manifest))
    mixed = {**board['shots'][0], 'id': 'shot5', 'visual': [{'asset_id': 'boy'}]}
    (root / 'storyboard.json').write_text(json.dumps({**board, 'shots': [board['shots'][0], mixed]}))
    await service.import_episode(ImportEpisode(directory=str(root), request_id='rich-third', confirmed=True))
    await variant.refresh_from_db()
    assert variant.chapter_numbers == [1, 2]
    assert all(a.source_chapters == [1, 2, 3] for a in await Asset.filter(novel_id=first['novel_id']))
    await AssetVariant.filter(id=variant.id).update(description='猫影本地形态手改')
    manifest.update(episode={'id': 'ep4', 'name': '第四集'}, number=4)
    (root / 'episode.json').write_text(json.dumps(manifest))
    with pytest.raises(SyncConflict, match='variant_changed'):
        await service.import_episode(ImportEpisode(directory=str(root), request_id='rich-fourth', confirmed=True))
    assert await Chapter.filter(novel_id=first['novel_id']).count() == 3
    assert all(a.source_chapters == [1, 2, 3] for a in await Asset.filter(novel_id=first['novel_id']))
    other_before = await Scene.filter(chapter_id=second['chapter_id']).values()
    # A newly read version permits a deliberate partial update without undoing local fields.
    await Scene.filter(id=target.id).update(prompt='本地确认的提示词')
    await target.refresh_from_db()
    (root / 'clip.mp4').unlink()
    updated = await service.update_shot(UpdateShot(directory=str(root), request_id='rich-update', confirmed=True,
        work_id='rich-work', episode_id='ep1', shot_id='shot4',
        base_version=await CreationObjects.recovery_version(target), changes={'description': '只改描述'}))
    await target.refresh_from_db()
    assert target.prompt == '本地确认的提示词'
    assert target.metadata['work_package']['voices'] == board['shots'][0]['voices']
    assert other_before == await Scene.filter(chapter_id=second['chapter_id']).values()
    assert updated['shots'][0]['version'] != first['shots'][0]['version']
    active = await Video.create(scene_id=target.id, model_type=1, status=1)
    with pytest.raises(ValueError, match='生成任务'):
        await service.update_shot(UpdateShot(directory=str(root), request_id='busy-update', confirmed=True,
            work_id='rich-work', episode_id='ep1', shot_id='shot4',
            base_version=await CreationObjects.recovery_version(target), changes={'description': '不能覆盖'}))
    assert await Video.filter(id=active.id, status=1).exists()


async def test_protocol_errors_and_schema_contract(tmp_path):
    from schemas.work_package import Assets, Episode, Storyboard
    published = json.loads(Path('prompts/skills/references/work_package.schema.json').read_text())
    for name, model in {'episode.json': Episode, 'assets.json': Assets, 'storyboard.json': Storyboard,
                        'import_episode': ImportEpisode, 'read_episode': ReadEpisode, 'update_shot': UpdateShot}.items():
        assert published[name] == model.model_json_schema()
    server = MCPServer(WorkSync(tmp_path, tmp_path))
    assert (await server.handle([]))['error']['code'] == -32600
    assert (await server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'ping', 'params': []}))['error']['code'] == -32602
    assert (await server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}))['result'] == {}
    await server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
    for name in ([], 'unknown'):
        result = await server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name}})
        assert result['error']['code'] == -32602
    assert (await server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'unknown'}))['error']['code'] == -32601
    missing = await server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'read_episode', 'arguments': {'work_id': 'missing', 'episode_id': 'missing'}}})
    assert missing['result']['isError']


async def test_receipt_origin_and_legacy_retry(tmp_path):
    from models.work_sync import WorkSyncRequest
    root = package(tmp_path / 'receipt', 'receipt-work')
    request = ImportEpisode(directory=str(root), request_id='receipt-import', confirmed=True)
    service = WorkSync(tmp_path, tmp_path / 'media', 'http://127.0.0.1:3012/studio/')
    first = await service.import_episode(request)
    saved = await WorkSyncRequest.get(request_id=request.request_id)
    old = {**saved.receipt, 'location': {**saved.receipt['location']}}
    old['location']['path'] = '/create/short-drama/storyboard/1?chapter=1'
    old['location'].pop('url')
    saved.receipt = old
    await saved.save(update_fields=['receipt'])
    assert await service.import_episode(request) == first
    assert first['location']['url'].startswith('http://127.0.0.1:3012/studio/#/')
    assert json.loads((root / 'sync-receipt.json').read_text()) == first
    for url in ('file:///tmp/site', 'http://user:secret@localhost', 'http://localhost/#/home'):
        with pytest.raises(ValueError):
            WorkSync(tmp_path, tmp_path, url)


@pytest.mark.parametrize('include_original', [False, True])
async def test_import_separates_source_and_director_script(tmp_path, include_original):
    root = package(tmp_path / 'pack', work=f'episode-docs-{include_original}')
    if include_original:
        manifest = json.loads((root/'episode.json').read_text())
        manifest['source_text'] = 'novel.txt'
        (root/'novel.txt').write_text('这是小说原文。')
        (root/'episode.json').write_text(json.dumps(manifest))
    service = WorkSync(tmp_path, tmp_path/'media')
    receipt = await service.import_episode(ImportEpisode(directory=str(root), request_id=f'two-docs-{include_original}', confirmed=True))
    chapter = await Chapter.get(id=receipt['chapter_id'])
    assert chapter.screenplay == (root/'screenplay.md').read_text()
    assert chapter.content == ('这是小说原文。' if include_original else '')


async def test_confirmed_style_and_shot_artwork_survive_import_and_partial_update(tmp_path):
    from models.novel import Novel
    root = package(tmp_path / 'artwork', work='artwork-work')
    manifest = json.loads((root / 'episode.json').read_text())
    manifest.update(style_key='xianxia-3d', storyboard_enabled=False)
    (root / 'episode.json').write_text(json.dumps(manifest))
    (root / 'sheet.png').write_bytes(b'test-sheet')
    (root / 'layout.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    board = json.loads((root / 'storyboard.json').read_text())
    board['shots'][0]['media'] = [{'path':'sheet.png','role':'storyboard'}, {'path':'layout.svg','role':'blocking'}]
    (root / 'storyboard.json').write_text(json.dumps(board))
    service = WorkSync(tmp_path, tmp_path/'media')
    receipt = await service.import_episode(ImportEpisode(directory=str(root), request_id='artwork-import', confirmed=True))
    project = await Novel.get(id=receipt['novel_id'])
    assert project.style_key == 'xianxia-3d' and not project.storyboard_enabled
    row = receipt['shots'][0]
    scene = await Scene.get(id=row['local_id'])
    sheet = scene.metadata['storyboard_sheet']
    assert sheet['image_url'] == receipt['archive']['sheet.png'] and sheet['video_guidance']
    assert scene.metadata['imported_media'][1]['url'] == receipt['archive']['layout.svg']
    base = dict(directory=str(root), confirmed=True, work_id='artwork-work', episode_id='ep1', shot_id=row['shot_id'])
    edited = await service.update_shot(UpdateShot(**base, base_version=row['version'], request_id='artwork-text', changes={'description':'修改说明'}))
    await scene.refresh_from_db()
    assert scene.metadata['storyboard_sheet'] == sheet
    await service.update_shot(UpdateShot(**base, base_version=edited['shots'][0]['version'], request_id='artwork-clear', changes={'media':[]}))
    await scene.refresh_from_db()
    assert 'storyboard_sheet' not in scene.metadata and scene.metadata['imported_media']==[]
