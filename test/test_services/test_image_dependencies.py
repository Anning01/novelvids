from unittest.mock import AsyncMock
import json

import pytest
from models.novel import Novel
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from schemas.work_package import Assets
from services.reference.dependencies import ReferenceGraph, bind_image_dependencies, image_dependencies_ready
from services.creation_agent.waiting import WaitingForDependencies
from services.ai_task_executor import AiTaskExecutor, BaseTaskHandler
from utils.enums import AiTaskTypeEnum


async def family():
    from uuid import uuid4
    novel = await Novel.create(name='身份一致性-' + str(uuid4()))
    asset = await Asset.create(novel=novel, canonical_name='赵无垢', asset_type=1)
    variant = await AssetVariant.create(asset=asset, name='十六年前')
    return novel, asset, variant


async def test_variant_waits_then_binds_current_main_image_without_changing_manual_order():
    novel, asset, variant = await family()
    params = {'novel_id': novel.id, 'asset_id': asset.id, 'variant_id': variant.id,
              'reference_images': ['/media/clothing.png']}
    with pytest.raises(WaitingForDependencies):
        await bind_image_dependencies(params)
    assert not await image_dependencies_ready(params)
    asset.main_image = '/media/confirmed-master.png'
    await asset.save()
    assert await image_dependencies_ready(params)
    await bind_image_dependencies(params)
    assert params['reference_images'] == ['/media/clothing.png', asset.main_image]
    assert params['image_reference_bindings'][0]['image_number'] == 2
    await bind_image_dependencies(params)
    assert len(params['reference_images']) == 2


async def test_dependency_graph_orders_all_sources_and_rejects_cycles_and_cross_project():
    novel, asset, variant = await family()
    prop = await Asset.create(novel=novel, canonical_name='剑', asset_type=3,
        metadata={'generation_reference_assets': [{'asset_id': asset.id, 'variant_id': variant.id}]})
    graph = await ReferenceGraph.load(novel.id)
    assert graph.ordered([(prop.id, None)]) == [(asset.id, None), (asset.id, variant.id), (prop.id, None)]
    variant.images = ['/ready.png']
    await variant.save()
    graph = await ReferenceGraph.load(novel.id)
    assert graph.missing_ordered([(prop.id, None)]) == [(prop.id, None)]
    assert graph.missing_ordered([(asset.id, variant.id)]) == []
    asset.metadata = {'generation_reference_assets': [{'asset_id': prop.id}]}
    await asset.save()
    with pytest.raises(ValueError, match='循环'):
        (await ReferenceGraph.load(novel.id)).ordered([(prop.id, None)])
    other, foreign, _ = await family()
    asset.metadata = {'generation_reference_assets': [{'asset_id': foreign.id}]}
    await asset.save()
    with pytest.raises(ValueError, match='当前项目'):
        (await ReferenceGraph.load(novel.id)).ordered([(asset.id, None)])


async def test_waiting_does_not_call_handler_or_create_external_receipts_and_survives_restart(monkeypatch):
    novel, asset, variant = await family()
    handler = AsyncMock(spec=BaseTaskHandler)
    handler.timeout_seconds = lambda _: None
    handler.execute.return_value = {'images': ['/media/young.png']}
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.reference_image, handler)
    params = {'novel_id': novel.id, 'asset_id': asset.id, 'variant_id': variant.id, 'prompt_language': 'zh'}
    task = await AiTask.create(task_type=2, status=1, request_params=params)
    await executor._run_once(task)
    await task.refresh_from_db()
    assert (task.status, task.stage) == (2, 'waiting_dependencies')
    handler.execute.assert_not_awaited()
    assert not await AgentOperation.filter(task=task, external=True).exists()
    # Failed upstream stays failed; dependency polling does not submit a new one.
    parent = await AiTask.create(task_type=2, status=4, request_params={'asset_id': asset.id})
    assert not await image_dependencies_ready(params)
    assert await AiTask.filter(id=parent.id, status=4).exists()
    # Boot recovery returns a durable waiting task to the queue; it waits again without a paid call.
    task.request_params = {**params, 'workflow_version': 'agent-skills-v1'}
    await task.save()
    from services.creation_agent.recovery import ProductionRecovery
    await ProductionRecovery().recover()
    await task.refresh_from_db()
    await executor._run_once(task)
    await task.refresh_from_db()
    assert task.stage == 'waiting_dependencies'
    handler.execute.assert_not_awaited()
    asset.main_image = '/media/uploaded-main.png'
    await asset.save()
    assert await image_dependencies_ready(params)
    # Exercise the executor's resumed path, bypassing unrelated agent configuration.
    task.status = 6
    task.request_params = params
    await task.save()
    monkeypatch.setattr(executor, '_complete', AsyncMock())
    await executor._run_once(task)
    assert handler.execute.await_args.args[0]['reference_images'] == [asset.main_image]


def test_mcp_dependency_contract_accepts_forward_references_and_rejects_invalid_graphs():
    data = {'assets': [
        {'id': 'prop', 'name': '剑', 'kind': 'item', 'prompt': '剑设定',
         'image_references': [{'asset_id': 'master', 'variant_id': 'young'}]},
        {'id': 'master', 'name': '赵无垢', 'kind': 'person', 'prompt': '64岁',
         'variants': [{'id': 'young', 'name': '十六年前', 'prompt': '48岁'}]},
    ]}
    assert Assets.model_validate(data).assets[0].image_references[0].variant_id == 'young'
    for ref in [{'asset_id': 'missing'}, {'asset_id': 'prop', 'variant_id': 'young'}, {'asset_id': 'master'}]:
        invalid = json.loads(json.dumps(data))
        invalid['assets'][1]['image_references'] = [ref]
        with pytest.raises(ValueError):
            Assets.model_validate(invalid)


def test_identity_prompt_preserves_target_age_and_uses_actual_image_index():
    from prompts.image_references import render_identity_references
    for language in ('zh', 'en'):
        text = render_identity_references([{'name': '赵无垢', 'image_number': 2}], language)
        assert '2' in text and '赵无垢' in text
        assert ('不能覆盖当前目标形态' in text) if language == 'zh' else ('must not override' in text)


async def test_confirmed_plan_keeps_variant_pending_after_base_failure_then_uses_uploaded_base(monkeypatch):
    from test.test_services.test_creation_plans import confirmed_fixture
    from schemas.creation_plan import CreationPlanStep
    from services.creation_agent.plan_execution import CreationPlanRunner
    conversation, _, plan, task, execution = await confirmed_fixture()
    asset = await Asset.create(novel_id=conversation.novel_id, canonical_name='师父', asset_type=1)
    variant = await AssetVariant.create(asset=asset, name='早年')
    plan.steps = [
        CreationPlanStep(id='base', operation='image', target_id=asset.id, label='主形象', instructions='生图'),
        CreationPlanStep(id='early', operation='image', target_id=asset.id, variant_id=variant.id,
                         label='早年', instructions='同一人物', depends_on=['base']),
    ]
    monkeypatch.setattr('services.creation_agent.plan_execution.load_plan', AsyncMock(return_value=plan))
    await AgentOperation.create(task=task, key='plan-step:base', state='completed', result={'status': 'failed', 'error': '供应商拒绝'})
    runner = CreationPlanRunner(execution)
    runner.target = AsyncMock(return_value={'kept': {'asset_ids': [asset.id], 'images': ['/early.png']}})
    with pytest.raises(WaitingForDependencies):
        await runner.run()
    runner.target.assert_not_awaited()
    assert not await AgentOperation.filter(task=task, key='plan-step:early').exists()
    asset.main_image = '/uploaded.png'
    await asset.save()
    result = await runner.run()
    assert not result['partial']
    assert runner.target.await_count == 1
    assert runner.target.await_args.args[1].id == 'early'
