import asyncio

import pytest
from fastapi import HTTPException

from controllers.scene import scene_controller
from models.asset import Asset
from models.scene import Scene
from models.video import Video
from schemas.scene import ScenePatch
from services.creation_objects import CreationObjects, project_write
from test.test_services.test_creation_object_lifecycle import objects


@pytest.mark.asyncio
async def test_page_delete_and_restore_keep_video_and_scene_bindings(client):
    _, _, asset, scenes = await objects()
    scene = scenes[0]
    await scene.assets.add(asset)
    video = await Video.create(scene=scene, model_type=1, status=3, url='keep.mp4')
    deleted = await client.delete(f'/api/scene/{scene.id}')
    assert deleted.json()['code'] == 0
    hidden = await client.get(f'/api/scene/{scene.id}')
    assert hidden.json()['code'] == 404
    assert await Video.filter(id=video.id).exists()
    active_videos = (await client.get('/api/video')).json()['data']['items']
    assert not any(item['id'] == video.id for item in active_videos)
    restored = await client.post(f'/api/scene/{scene.id}/restore')
    assert restored.json()['code'] == 0
    assert restored.json()['data']['assets'][0]['id'] == asset.id


@pytest.mark.asyncio
async def test_page_cannot_bind_archived_or_foreign_asset(client):
    novel, _, asset, scenes = await objects()
    async with project_write(novel.id):
        await CreationObjects(novel.id).archive('asset', asset.id)
    response = await client.patch(f'/api/scene/{scenes[0].id}', json={'asset_ids': [asset.id]})
    assert response.json()['code'] == 409
    assert await scenes[0].assets.all().count() == 0
    assert (await client.post(f'/api/asset/{asset.id}/restore')).json()['code'] == 0


@pytest.mark.asyncio
async def test_concurrent_page_binding_and_agent_delete_never_leave_active_dangling_reference():
    novel, _, asset, scenes = await objects()
    async def archive():
        async with project_write(novel.id):
            await CreationObjects(novel.id).archive('asset', asset.id)
    results = await asyncio.gather(archive(), scene_controller.patch(scenes[0].id, ScenePatch(asset_ids=[asset.id])), return_exceptions=True)
    assert sum(isinstance(result, (ValueError, HTTPException)) for result in results) == 1
    active = await Asset.filter(id=asset.id).exists()
    bound = await Scene.filter(id=scenes[0].id, assets__id=asset.id).exists()
    assert active or not bound
