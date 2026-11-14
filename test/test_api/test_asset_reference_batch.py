from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.ai_task import AiTask
from models.config import AiModelConfig
from models.novel import Novel
from models.agent_submission import AgentSubmission
from controllers.asset import asset_controller


async def batch_fixture():
    novel = await Novel.create(name='Batch survives browser close')
    assets = [await Asset.create(novel=novel, canonical_name=f'Asset {i}', asset_type=i % 3 + 1) for i in range(7)]
    config = await AiModelConfig.create(task_type=2, name='batch-model', model='test', api_key='test-key',
        base_url='https://example.invalid', image_model_type='gpt_image_2', is_active=True)
    payload = {'novel_id': novel.id, 'asset_ids': [a.id for a in assets], 'model_config_id': config.id,
               'clarity': 'medium', 'aspect_ratio': '1:1', 'output_format': 'png'}
    return assets, payload


@pytest.mark.asyncio
async def test_entire_batch_is_durable_before_reply_and_retries_reuse_tasks(client, configured_creation_agent):
    assets, payload = await batch_fixture()
    assets[0].main_image = '/media/existing.png'
    await assets[0].save()
    headers = {'X-Creation-Request-Id': str(uuid4())}
    with patch('services.ai_task_executor.ai_task_executor.run', new_callable=AsyncMock) as run:
        first = await client.post('/api/asset/reference-batch', json=payload, headers=headers)
        assert first.json()['code'] == 0, first.text
        data = first.json()['data']
        assert len(data['tasks']) == 6
        assert data['skipped_asset_ids'] == [assets[0].id]
        assert {task['request_params']['asset_id'] for task in data['tasks']} == {a.id for a in assets[1:]}
        assert await AiTask.filter(task_type=2, status=1).count() == 6
        assert len(await asset_controller.active_generations(payload['novel_id'])) == 6
        for task in await AiTask.filter(task_type=2):
            assert task.request_params['workflow_version'] == 'agent-skills-v1'
            assert not task.request_params.get('parent_task_id')
        from services.creation_agent.recovery import ProductionRecovery
        await ProductionRecovery().recover()
        assert await AiTask.filter(task_type=2, status=6).count() == 6
        second = await client.post('/api/asset/reference-batch', json=payload, headers=headers)
        assert [t['id'] for t in second.json()['data']['tasks']] == [t['id'] for t in data['tasks']]
        # A new batch skips active tasks, including runs already assigned a plan.
        await AiTask.filter(id=data['tasks'][0]['id']).update(request_params={
            **data['tasks'][0]['request_params'], 'creation_plan_id': data['tasks'][0]['id']})
        third = await client.post('/api/asset/reference-batch', json=payload,
            headers={'X-Creation-Request-Id': str(uuid4())})
        assert third.json()['data']['tasks'] == []
        assert set(third.json()['data']['skipped_asset_ids']) == {a.id for a in assets}
        assert await AiTask.filter(task_type=2).count() == 6
        run.assert_not_awaited()
    assert 'test-key' not in first.text
    changed = await client.post('/api/asset/reference-batch', json={**payload, 'aspect_ratio': '3:2'}, headers=headers)
    assert changed.json()['code'] == 409


@pytest.mark.asyncio
async def test_batch_rejects_cross_project_ids_without_any_submission(client, configured_creation_agent):
    assets, payload = await batch_fixture()
    other = await Novel.create(name='Other')
    foreign = await Asset.create(novel=other, canonical_name='Private', asset_type=1)
    response = await client.post('/api/asset/reference-batch', json={**payload, 'asset_ids': [assets[0].id, foreign.id]})
    assert response.json()['code'] == 404, response.text
    assert await AiTask.filter(task_type=2).count() == 0
    await assets[0].refresh_from_db()
    assert not assets[0].metadata


@pytest.mark.asyncio
async def test_failed_admission_rolls_back_the_whole_queue_and_settings(client, configured_creation_agent):
    assets, payload = await batch_fixture()
    original = asset_controller.reference
    async def submit(identifier, **kwargs):
        if identifier == assets[2].id:
            raise HTTPException(409, 'Selected model is unavailable')
        return await original(identifier, **kwargs)
    with patch.object(asset_controller, 'reference', side_effect=submit):
        response = await client.post('/api/asset/reference-batch', json=payload,
            headers={'X-Creation-Request-Id': str(uuid4())})
    assert response.json()['code'] == 409, response.text
    assert await AiTask.filter(task_type=2).count() == 0
    assert await AgentSubmission.all().count() == 0
    for asset in assets:
        await asset.refresh_from_db()
        assert not asset.metadata


@pytest.mark.asyncio
async def test_analysis_reference_in_batch_prevents_partial_paid_queue(client, configured_creation_agent):
    assets, payload = await batch_fixture()
    assets[-1].metadata = {'analysis_source': 'project_analysis'}
    await assets[-1].save()
    response = await client.post('/api/asset/reference-batch', json=payload,
        headers={'X-Creation-Request-Id': str(uuid4())})
    assert response.json()['code'] == 409, response.text
    assert await AiTask.filter(task_type=2).count() == 0
    assert await AgentSubmission.all().count() == 0
    await assets[0].refresh_from_db()
    assert not assets[0].metadata


@pytest.mark.asyncio
async def test_batch_submits_base_and_variants_and_skips_only_finished_or_active_targets(client, configured_creation_agent):
    assets, payload = await batch_fixture()
    asset = assets[0]
    variants = [await AssetVariant.create(asset=asset, name=f'Form {i}',
        metadata={'model_config_id': 99999, 'aspect_ratio': '9:16'}) for i in range(3)]
    variants[1].images = ['/media/existing-form.png']
    await variants[1].save()
    payload.update(asset_ids=[asset.id], variant_ids=[v.id for v in variants] + [variants[0].id])
    headers = {'X-Creation-Request-Id': str(uuid4())}
    first = await client.post('/api/asset/reference-batch', json=payload, headers=headers)
    assert first.json()['code'] == 0, first.text
    data = first.json()['data']
    assert {t['request_params']['variant_id'] for t in data['tasks']} == {None, variants[0].id, variants[2].id}
    assert data['skipped_variant_ids'] == [variants[1].id]
    for task in data['tasks']:
        assert task['request_params']['model_config_id'] == payload['model_config_id']
        assert task['request_params']['aspect_ratio'] == '1:1'
    retry = await client.post('/api/asset/reference-batch', json=payload, headers=headers)
    assert [t['id'] for t in retry.json()['data']['tasks']] == [t['id'] for t in data['tasks']]
    second = await client.post('/api/asset/reference-batch', json=payload)
    assert second.json()['data']['tasks'] == []
    assert set(second.json()['data']['skipped_variant_ids']) == {v.id for v in variants}
    # A completed base image must not prevent submitting another empty form.
    asset.main_image = '/media/base.png'
    await asset.save()
    new_form = await AssetVariant.create(asset=asset, name='Another form')
    third = await client.post('/api/asset/reference-batch', json={**payload, 'asset_ids': [], 'variant_ids': [new_form.id]})
    assert third.json()['code'] == 0, third.text
    assert len(third.json()['data']['tasks']) == 1
    assert third.json()['data']['tasks'][0]['request_params']['variant_id'] == new_form.id


@pytest.mark.asyncio
async def test_batch_validates_variant_project_before_submitting_any_target(client, configured_creation_agent):
    assets, payload = await batch_fixture()
    other = await Novel.create(name='Other project')
    foreign = await Asset.create(novel=other, canonical_name='Foreign asset', asset_type=1)
    variant = await AssetVariant.create(asset=foreign, name='Foreign form')
    response = await client.post('/api/asset/reference-batch', json={**payload, 'variant_ids': [variant.id]})
    assert response.json()['code'] == 404, response.text
    assert await AiTask.all().count() == 0
    await assets[0].refresh_from_db()
    assert not assets[0].metadata


@pytest.mark.asyncio
async def test_batch_requires_at_least_one_base_or_variant(client):
    _, payload = await batch_fixture()
    response = await client.post('/api/asset/reference-batch', json={**payload, 'asset_ids': [], 'variant_ids': []})
    assert response.json()['code'] == 422, response.text


@pytest.mark.asyncio
async def test_variant_admission_failure_rolls_back_base_queue_and_form_settings(client, configured_creation_agent):
    assets, payload = await batch_fixture()
    variant = await AssetVariant.create(asset=assets[0], name='Rejected form', metadata={'aspect_ratio': '9:16'})
    original = asset_controller.reference

    async def submit(identifier, **kwargs):
        if kwargs.get('variant_id') == variant.id:
            raise HTTPException(409, 'Selected model is unavailable')
        return await original(identifier, **kwargs)

    with patch.object(asset_controller, 'reference', side_effect=submit):
        response = await client.post('/api/asset/reference-batch', json={**payload, 'variant_ids': [variant.id]},
            headers={'X-Creation-Request-Id': str(uuid4())})
    assert response.json()['code'] == 409, response.text
    assert await AiTask.all().count() == 0
    assert await AgentSubmission.all().count() == 0
    await variant.refresh_from_db()
    assert variant.metadata == {'aspect_ratio': '9:16'}
    await assets[0].refresh_from_db()
    assert not assets[0].metadata
