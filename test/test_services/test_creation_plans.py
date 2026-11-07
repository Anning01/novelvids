"""Creative plans keep evidence, permissions and generation inputs connected."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.chapter import Chapter
from models.creation_agent import AgentMessage
from schemas.creation_plan import (
    CreationBrief, CreationPlanDraft, CreativeRequirement, PlanConfirmation, SourceReading,
)
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.plans import CreationPlanner, confirmed_plan, plan_proposal
from services.creation_agent.sessions import agent_sessions
from services.creation_agent.skill_execution import SkillExecution
from test.test_services.test_creation_agent_sessions import session_fixture


async def plan_fixture():
    conversation, request, _ = await session_fixture()
    first = await Chapter.get(id=request.chapter_id)
    chapters = [first]
    for number in range(2, 11):
        chapters.append(await Chapter.create(novel_id=conversation.novel_id, number=number,
            name=f'第{number}章', content='城门崩塌，主角救出同伴。' if number == 8 else f'第{number}章主角追查来信。'))
    request = request.model_copy(update={'write_scope': 'chapter', 'targets': [],
        'message': '生成全书分镜，阅读前十章，把高潮放第一章，再切回开头。'})
    task = await agent_sessions.submit(conversation, request, AuthContext())
    await AiTask.filter(id=task.id).update(status=2)
    source = await AgentMessage.get(task=task, role='user')
    assistant = await AgentMessage.get(task=task, role='assistant')
    execution = SkillExecution(task.request_params, assistant, AsyncMock())
    return conversation, request, chapters, task, source, execution


def plan_model(request, chapters):
    async def generate(skill, facts, output_type, **_):
        if skill == 'planning_request':
            return CreationBrief(operations=['storyboard'], read_chapter_ids=[c.id for c in chapters],
                write_chapter_ids=[chapters[0].id], project_scope_quote='生成全书分镜',
                requirements=[CreativeRequirement(id='opening', instruction='高潮前置，再切回起点',
                    source_quote='把高潮放第一章，再切回开头', chapter_ids=[chapters[0].id], acceptance='开头出现城门崩塌，随后返回收信')])
        if skill == 'source_reading':
            return SourceReading(summary=facts['content'], candidates=[{'chapter_id': facts['chapter_id'],
                'start': facts['start'], 'end': facts['end']}])
        if skill == 'creation_planning':
            return CreationPlanDraft(summary='以第八章城门崩塌开场，救援中切回收到来信。', steps=[{
                'id': 'chapter1', 'operation': 'storyboard', 'target_id': chapters[0].id, 'mode': 'revise',
                'requirement_ids': ['opening'], 'sources': [{'chapter_id': chapters[7].id, 'start': 0, 'end': len(chapters[7].content)}],
                'instructions': '城门崩塌开场，救援中切回收到来信。', 'label': '重做第一章分镜'}])
        raise AssertionError(skill)
    return generate


@pytest.mark.asyncio
async def test_ten_chapter_plan_keeps_complete_reading_and_exact_selected_source():
    conversation, request, chapters, task, source, execution = await plan_fixture()
    generate = AsyncMock(side_effect=plan_model(request, chapters))
    with patch.object(execution, 'generate', generate):
        plan = await CreationPlanner(execution, source).prepare(request)
        replay = await CreationPlanner(execution, source).prepare(request)
    assert replay == plan
    assert len([c for c in generate.call_args_list if c.args[0] == 'source_reading']) == 10
    assert len(plan.chapters) == 10
    assert all(item.coverage[0][0] == 0 and item.coverage[-1][1] == item.characters for item in plan.chapters)
    assert plan.excerpts[0].text == chapters[7].content
    assert plan.steps[0].target_id == chapters[0].id
    proposal = await plan_proposal(task.id)
    confirmation = PlanConfirmation.model_validate(proposal['plan_confirmation'])
    assert await confirmed_plan(conversation, confirmation) == plan
    await Chapter.filter(id=chapters[7].id).update(content='正文被用户修改')
    with pytest.raises(HTTPException, match='原文已变化'):
        await confirmed_plan(conversation, confirmation)


@pytest.mark.asyncio
async def test_foreign_or_stale_confirmation_rejected():
    conversation, request, chapters, task, source, execution = await plan_fixture()
    with patch.object(execution, 'generate', side_effect=plan_model(request, chapters)):
        await CreationPlanner(execution, source).prepare(request)
    with pytest.raises(HTTPException):
        await confirmed_plan(conversation, PlanConfirmation(task_id=task.id, revision='0' * 64))
    other = await agent_sessions.create(conversation.novel_id, AuthContext())
    proposal = await plan_proposal(task.id)
    with pytest.raises(HTTPException):
        await confirmed_plan(other, PlanConfirmation.model_validate(proposal['plan_confirmation']))


@pytest.mark.asyncio
async def test_partial_or_invalid_read_never_becomes_completed_plan():
    _, request, chapters, task, source, execution = await plan_fixture()
    model = plan_model(request, chapters)
    async def broken(skill, facts, output_type, **kwargs):
        if skill == 'source_reading':
            return SourceReading(summary='猜测', candidates=[{'chapter_id': facts['chapter_id'], 'start': 0, 'end': facts['end'] + 1}])
        return await model(skill, facts, output_type, **kwargs)
    with patch.object(execution, 'generate', side_effect=broken), pytest.raises(ValueError, match='之外'):
        await CreationPlanner(execution, source).prepare(request)
    assert not await AgentOperation.filter(task=task, key='creation:plan').exists()


@pytest.mark.asyncio
async def test_read_only_does_not_plan_or_call_models():
    _, request, _, _, source, execution = await plan_fixture()
    with patch.object(execution, 'generate', AsyncMock()) as generate, pytest.raises(ValueError, match='只读'):
        await CreationPlanner(execution, source).prepare(request.model_copy(update={'write_scope': 'read_only'}))
    generate.assert_not_called()


def test_dependency_cycles_and_fabricated_future_ids_rejected():
    with pytest.raises(ValueError):
        CreationPlanDraft(summary='错误方案', steps=[{'id': 'a', 'operation': 'video', 'source_step': 'b',
            'depends_on': ['b'], 'instructions': '生成', 'label': '生成'}])


async def confirmed_fixture():
    conversation, request, chapters, task, source, execution = await plan_fixture()
    with patch.object(execution, 'generate', side_effect=plan_model(request, chapters)):
        plan = await CreationPlanner(execution, source).prepare(request)
    await AiTask.filter(id=task.id).update(status=3)
    proposal = await plan_proposal(task.id)
    confirmation = request.model_copy(update={'request_id': uuid4(), 'message': proposal['message'],
        'plan_confirmation': PlanConfirmation.model_validate(proposal['plan_confirmation'])})
    runner = await agent_sessions.submit(conversation, confirmation, AuthContext())
    await AiTask.filter(id=runner.id).update(status=2)
    message = await AgentMessage.get(task=runner, role='assistant')
    return conversation, confirmation, plan, runner, SkillExecution(runner.request_params, message, AsyncMock())


@pytest.mark.asyncio
async def test_confirmation_is_idempotent_and_foreign_replay_never_leaks_task():
    conversation, request, _, task, _ = await confirmed_fixture()
    again = await agent_sessions.submit(conversation, request, AuthContext())
    assert again.id == task.id
    await AiTask.filter(id=task.id).update(status=3)
    changed_id = request.model_copy(update={'request_id': uuid4()})
    assert (await agent_sessions.submit(conversation, changed_id, AuthContext())).id == task.id
    other = await agent_sessions.create(conversation.novel_id, AuthContext())
    with pytest.raises(HTTPException, match='当前会话'):
        await agent_sessions.submit(other, changed_id, AuthContext())


@pytest.mark.asyncio
async def test_runner_resumes_receipts_without_duplicate_submission():
    from services.creation_agent.plan_execution import CreationPlanRunner
    from services.creation_agent.waiting import WaitingForDependencies
    from services.creation_agent.step_context import step_context
    from services.creation_agent.skill_execution import current_execution
    _, _, plan, task, execution = await confirmed_fixture()
    children = []
    async def submit(intent, **kwargs):
        inherited = current_execution.get().params
        child = await AiTask.create(task_type=3, status=6, request_params={**inherited, 'chapter_id': intent.target_id})
        await AgentOperation.create(task=task, key='submit:' + str(intent.request_id), state='completed', result={'task_id': str(child.id)})
        children.append(child)
        context = await step_context(child.request_params)
        assert context.sources[0].text == '城门崩塌，主角救出同伴。'
        assert context.requirements[0].id == 'opening'
        assert '切回' in context.step.instructions
        return {'task_id': str(child.id)}
    with patch('services.creation_agent.plan_execution.submit_intent', side_effect=submit) as submitter:
        for _ in range(2):
            with pytest.raises(WaitingForDependencies):
                await CreationPlanRunner(execution).run()
        assert submitter.await_count == 1
        await AiTask.filter(id=children[0].id).update(status=3, response_data={'scene_ids': []})
        result = await CreationPlanRunner(execution).run()
        replay = await CreationPlanRunner(execution).run()
    assert result == replay
    assert result['partial'] is False
    assert submitter.await_count == 1


@pytest.mark.asyncio
async def test_runner_preserves_existing_content_and_stops_on_cancel():
    from services.creation_agent.plan_execution import CreationPlanRunner
    _, _, plan, task, execution = await confirmed_fixture()
    plan.steps[0].mode = 'fill_missing'
    plan.steps[0].requirement_ids = []
    plan.steps[0].instructions = '保留已有分镜'
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    with patch('services.creation_agent.plan_execution.submit_intent', AsyncMock()) as submitter:
        result = await CreationPlanRunner(execution).run()
        assert result['steps'][0]['status'] == 'skipped'
        submitter.assert_not_called()
        execution.before_request = AsyncMock(side_effect=ValueError('任务已停止'))
        with pytest.raises(ValueError, match='已停止'):
            await CreationPlanRunner(execution).run()


@pytest.mark.asyncio
async def test_failed_dependency_blocks_only_its_dependents():
    from services.creation_agent.plan_execution import CreationPlanRunner
    from schemas.creation_plan import CreationPlanStep
    _, _, plan, task, execution = await confirmed_fixture()
    plan.steps += [CreationPlanStep(id='video', operation='video', source_step='chapter1', depends_on=['chapter1'],
        label='生成第一章视频', instructions='按分镜生成'), plan.steps[0].model_copy(update={'id': 'independent', 'mode': 'fill_missing', 'requirement_ids': [], 'instructions': '保留已有分镜'})]
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    await AgentOperation.create(task=task, key='plan-step:chapter1', state='completed', result={'status': 'failed', 'error': '检查未通过'})
    result = await CreationPlanRunner(execution).run()
    assert [row['status'] for row in result['steps']] == ['failed', 'blocked', 'skipped']
    assert result['partial'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('repair_passes', [True, False])
async def test_semantic_review_repairs_once_and_keeps_rejected_candidate(repair_passes):
    from schemas.agent_workflow import CompletePrompt
    from schemas.creation_plan import CreativeCheck, CreationStepContext
    from services.creation_agent.creative_checks import generate_checked, CreativeCandidateRejected
    _, _, plan, _, execution = await confirmed_fixture()
    context = CreationStepContext(step=plan.steps[0], original_message='原始要求', requirements=plan.brief.requirements, sources=plan.excerpts)
    calls = []
    async def generate(skill, facts, output_type, **kwargs):
        calls.append(skill)
        if skill == 'creative_check':
            passed = facts['segment'].endswith(':1') and repair_passes
            return CreativeCheck(plan_followed=passed, issues=[] if passed else ['缺少切回点'],
                findings=[{'requirement_id': 'opening', 'passed': passed, 'location': 'prompt', 'detail': '检查切回点'}])
        return CompletePrompt(prompt='城门崩塌，随后切回收到来信。' if len(calls) > 1 else '仅城门崩塌。')
    with patch.object(execution, '_generate', side_effect=generate):
        if repair_passes:
            result = await generate_checked(execution, 'video', {}, CompletePrompt, {}, context)
            assert '切回' in result.prompt
        else:
            with pytest.raises(CreativeCandidateRejected, match='未覆盖'):
                await generate_checked(execution, 'video', {}, CompletePrompt, {}, context)
    assert calls == ['video', 'creative_check', 'video', 'creative_check']
    saved = await AgentOperation.filter(task_id=execution.params['task_id'], key__startswith='creative-check:').order_by('id')
    assert len(saved) == 2
    assert 'candidate' in saved[1].result


@pytest.mark.asyncio
async def test_cross_chapter_assets_do_not_change_original_source_chapters():
    from models.asset import Asset
    from services.creation_agent.step_context import context_assets
    _, _, plan, _, execution = await confirmed_fixture()
    asset = await Asset.create(novel_id=plan.novel_id, asset_type=2, canonical_name='城门', source_chapters=[8], base_traits='破损的城门')
    plan.steps[0].asset_ids = [asset.id]
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    params = {**execution.params, 'creation_step_id': 'chapter1', 'chapter_id': plan.steps[0].target_id}
    assert asset.id in [item.id for item in await context_assets(params)]
    await asset.refresh_from_db()
    assert asset.source_chapters == [8]


@pytest.mark.asyncio
async def test_missing_requested_chapter_number_is_not_silently_omitted():
    _, request, chapters, _, source, execution = await plan_fixture()
    model = plan_model(request, chapters)
    async def generate(skill, facts, output_type, **kwargs):
        value = await model(skill, facts, output_type, **kwargs)
        if skill == 'planning_request':
            value.read_chapter_numbers = list(range(1, 12))
        return value
    with patch.object(execution, 'generate', side_effect=generate), pytest.raises(ValueError, match='尚未导入'):
        await CreationPlanner(execution, source).prepare(request)


@pytest.mark.asyncio
async def test_project_scope_resolves_all_real_chapters_and_rejects_incomplete_plan():
    _, request, chapters, _, source, execution = await plan_fixture()
    model = plan_model(request, chapters)
    async def generate(skill, facts, output_type, **kwargs):
        if skill == 'creation_planning':
            assert facts['brief']['write_chapter_ids'] == [row.id for row in chapters]
        value = await model(skill, facts, output_type, **kwargs)
        if skill == 'planning_request':
            value.write_selection = 'project'
        return value
    with patch.object(execution, 'generate', side_effect=generate), pytest.raises(ValueError, match='遗漏'):
        await CreationPlanner(execution, source).prepare(request)


@pytest.mark.asyncio
async def test_confirmed_runner_finishes_protocol_and_releases_conversation():
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.handler import CreationAgentTaskHandler
    from services.creation_agent.event_log import agent_event_log
    from utils.enums import AiTaskTypeEnum
    conversation, _, plan, task, execution = await confirmed_fixture()
    plan.steps[0].mode = 'fill_missing'
    plan.steps[0].requirement_ids = []
    plan.steps[0].instructions = '保留已有分镜'
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    await AiTask.filter(id=task.id).update(status=6)
    await task.refresh_from_db()
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    await conversation.refresh_from_db()
    assert task.status == 3, task.error_message
    assert conversation.active_task_id is None
    message = await AgentMessage.get(task=task, role='assistant')
    events = await agent_event_log.load(message)
    assert events[0]['type'] == 'RUN_STARTED'
    assert events[-1]['type'] == 'RUN_FINISHED'
    assert '已有成果' in message.content


@pytest.mark.asyncio
async def test_waiting_plan_survives_timeout_cleanup_and_process_restart():
    from datetime import datetime, timedelta, timezone
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.handler import CreationAgentTaskHandler
    from services.creation_agent.recovery import ProductionRecovery
    from utils.enums import AiTaskTypeEnum
    _, _, _, task, _ = await confirmed_fixture()
    started = datetime.now(timezone.utc) - timedelta(hours=1)
    await AiTask.filter(id=task.id).update(stage='waiting_dependencies', started_at=started)
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.cleanup_stale_tasks(AiTaskTypeEnum.creation_agent)
    await executor.fail_stale_on_boot()
    await task.refresh_from_db()
    assert task.status == 2
    await ProductionRecovery().recover()
    await task.refresh_from_db()
    assert task.status == 6 and task.stage == 'resuming'
    assert task.started_at == started


@pytest.mark.asyncio
@pytest.mark.parametrize('violation', ['operation', 'requirement', 'scope', 'asset', 'variant'])
async def test_plan_rejects_unrequested_operations_and_fabricated_references(violation):
    _, request, chapters, _, source, execution = await plan_fixture()
    model = plan_model(request, chapters)
    async def generate(skill, facts, output_type, **kwargs):
        value = await model(skill, facts, output_type, **kwargs)
        if skill == 'creation_planning':
            step = value.steps[0]
            if violation == 'operation':
                value.steps.append(step.model_copy(update={'id': 'extra', 'operation': 'video'}))
            elif violation == 'requirement':
                step.requirement_ids = ['invented']
            elif violation == 'scope':
                step.target_id = chapters[1].id
            elif violation == 'asset':
                step.asset_ids = [999999]
            else:
                step.variant_ids = [999999]
        return value
    with patch.object(execution, 'generate', side_effect=generate), pytest.raises(ValueError):
        await CreationPlanner(execution, source).prepare(request)


@pytest.mark.asyncio
async def test_existing_storyboard_is_not_reported_as_fulfilling_a_missing_requirement():
    from schemas.creation_plan import CreativeCheck
    from services.creation_agent.plan_execution import CreationPlanRunner
    _, _, plan, _, execution = await confirmed_fixture()
    plan.steps[0].mode = 'fill_missing'
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    report = CreativeCheck(plan_followed=False, findings=[{'requirement_id': 'opening', 'passed': False,
        'location': '未找到', 'detail': '旧分镜没有倒叙开场'}], issues=['缺少倒叙开场'])
    with patch.object(SkillExecution, '_generate', AsyncMock(return_value=report)), \
         patch('services.creation_agent.plan_execution.submit_intent', AsyncMock()) as submitter:
        result = await CreationPlanRunner(execution).run()
    assert result['partial'] is True
    assert result['steps'][0]['status'] == 'failed'
    assert '已有成果未落实' in result['steps'][0]['error']
    submitter.assert_not_called()


@pytest.mark.asyncio
async def test_quote_resolves_exact_offsets_instead_of_trusting_model_arithmetic():
    from services.creation_agent.plan_sources import CreationSourceLoader
    _, _, chapters, _, _, execution = await plan_fixture()
    quote = '主角救出同伴'
    result = SourceReading(summary='救援高潮', candidates=[{'chapter_id': chapters[7].id, 'start': 0, 'end': 1, 'quote': quote}])
    with patch.object(execution, 'generate', AsyncMock(return_value=result)):
        evidence = await CreationSourceLoader(execution).read([chapters[7].id], [])
    selection = evidence[0].pages[0].candidates[0]
    assert chapters[7].content[selection.start:selection.end] == quote
    excerpts = await CreationSourceLoader(execution).excerpts([selection], evidence)
    assert excerpts[0].text == quote


@pytest.mark.asyncio
async def test_fill_missing_assets_keeps_existing_prompt_and_returns_real_ids():
    from models.asset import Asset
    from services.extraction.persistence import AssetUpsertService
    from services.extraction.extractor import AssetExtractionResult, Person
    conversation, _, _, _, _, _ = await plan_fixture()
    asset = await Asset.create(novel_id=conversation.novel_id, asset_type=1, canonical_name='主角',
        base_traits='用户已有的完整设计', source_chapters=[8])
    result = AssetExtractionResult(persons=[Person(name='主角', base_traits='模型试图覆盖'), Person(name='同伴', base_traits='新人物设计')], scenes=[], items=[])
    summary = await AssetUpsertService().save_result(novel_id=conversation.novel_id, chapter_number=8,
        result=result, preserve_existing=True, include_ids=True)
    await asset.refresh_from_db()
    assert asset.base_traits == '用户已有的完整设计'
    assert summary['persons'][0] == {'name': '主角', 'action': 'preserved', 'asset_id': asset.id}
    assert summary['persons'][1]['action'] == 'created'
    assert await Asset.filter(id=summary['persons'][1]['asset_id'], novel_id=conversation.novel_id).exists()


@pytest.mark.asyncio
async def test_dynamic_media_targets_continue_after_one_submission_fails():
    from models.scene import Scene
    from schemas.creation_plan import CreationPlanStep
    from services.creation_agent.plan_execution import CreationPlanRunner
    from services.creation_agent.waiting import WaitingForDependencies
    _, _, plan, task, execution = await confirmed_fixture()
    scenes = [await Scene.create(chapter_id=plan.steps[0].target_id, sequence=i, prompt='已有提示词', duration=6) for i in (2, 3, 4)]
    plan.steps.append(CreationPlanStep(id='videos', operation='video', source_step='chapter1', depends_on=['chapter1'],
        mode='regenerate', label='生成新分镜的视频', instructions='沿用已确认分镜'))
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    await AgentOperation.create(task=task, key='plan-step:chapter1', state='completed', result={'status': 'completed', 'scene_ids': [s.id for s in scenes]})
    children = []
    async def submit(intent, **kwargs):
        if intent.target_id == scenes[1].id:
            raise ValueError('第二条素材已失效')
        child = await AiTask.create(task_type=4, status=2, request_params={})
        children.append(child)
        await AgentOperation.create(task=task, key='submit:' + str(intent.request_id), state='completed', result={'task_id': str(child.id)})
        return {'task_id': str(child.id)}
    with patch('services.creation_agent.plan_execution.submit_intent', side_effect=submit) as submitter:
        for _ in range(2):
            with pytest.raises(WaitingForDependencies):
                await CreationPlanRunner(execution).run()
        assert submitter.await_count == 3 and len(children) == 2
        await AiTask.filter(id__in=[child.id for child in children]).update(status=3, response_data={'url': '/media/result.mp4'})
        result = await CreationPlanRunner(execution).run()
    assert result['partial'] is True
    assert len(result['steps'][1]['outputs']) == 2
    assert '失效' in result['steps'][1]['error']


@pytest.mark.asyncio
async def test_dynamic_target_versions_do_not_cross_contaminate_sibling_media():
    from models.asset import Asset
    from schemas.creation_plan import CreationPlanStep
    from services.creation_agent.object_state import object_version
    from services.creation_agent.step_context import validate_step_inputs
    _, _, plan, task, execution = await confirmed_fixture()
    assets = [await Asset.create(novel_id=plan.novel_id, asset_type=1, canonical_name=name, base_traits='原设计') for name in ['甲', '乙']]
    plan.steps[0].operation = 'assets'
    plan.steps.append(CreationPlanStep(id='images', operation='image', source_step='chapter1', depends_on=['chapter1'],
        mode='revise', label='生成资产图片', instructions='调整光线'))
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    await AgentOperation.create(task=task, key='plan-step:chapter1', state='completed', result={'status': 'completed',
        'asset_ids': [asset.id for asset in assets], 'object_versions': {f'asset:{asset.id}': await object_version(asset) for asset in assets}})
    await Asset.filter(id=assets[0].id).update(base_traits='甲的已更新设计')
    params = {**execution.params, 'creation_step_id': 'images', 'asset_id': assets[1].id}
    await validate_step_inputs(params)
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs({**params, 'asset_id': assets[0].id})


@pytest.mark.asyncio
async def test_completed_image_hands_updated_asset_version_to_dependents():
    from models.asset import Asset
    from services.creation_agent.object_state import object_version
    from services.creation_agent.plan_execution import CreationPlanRunner
    _, _, plan, _, execution = await confirmed_fixture()
    asset = await Asset.create(novel_id=plan.novel_id, canonical_name='城门', asset_type=2, base_traits='城门设计')
    plan.steps[0].operation = 'image'
    plan.steps[0].target_id = asset.id
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    async def submit(intent, **kwargs):
        await Asset.filter(id=asset.id).update(main_image='/media/new-reference.png')
        child = await AiTask.create(task_type=2, status=3, request_params={}, response_data={'images': ['/media/new-reference.png']})
        return {'task_id': str(child.id)}
    with patch('services.creation_agent.plan_execution.submit_intent', side_effect=submit):
        result = await CreationPlanRunner(execution).run()
    await asset.refresh_from_db()
    assert result['steps'][0]['asset_ids'] == [asset.id]
    assert result['steps'][0]['object_versions'][f'asset:{asset.id}'] == await object_version(asset)


@pytest.mark.asyncio
async def test_prepared_plan_cannot_be_reported_as_completed_generation(monkeypatch):
    from pydantic_ai.models.function import FunctionModel
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.handler import CreationAgentTaskHandler
    from utils.enums import AiTaskTypeEnum
    _, request, chapters, task, source, execution = await plan_fixture()
    with patch.object(execution, 'generate', side_effect=plan_model(request, chapters)):
        await CreationPlanner(execution, source).prepare(request)
    async def misleading_reply(messages, info):
        yield '全部分镜已生成。'
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=misleading_reply))
    await AiTask.filter(id=task.id).update(status=6)
    await task.refresh_from_db()
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    reply = await AgentMessage.get(task=task, role='assistant')
    assert '确认执行' in reply.content and '全部分镜已生成' not in reply.content
    assert await plan_proposal(task.id) is not None


@pytest.mark.asyncio
async def test_broad_production_request_enters_planner_before_chat_can_write(monkeypatch):
    from models.scene import Scene
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.handler import CreationAgentTaskHandler
    from utils.enums import AiTaskTypeEnum
    _, request, chapters, task, _, _ = await plan_fixture()
    respond = plan_model(request, chapters)
    async def generate(self, skill, facts, output_type, **kwargs):
        return await respond(skill, facts, output_type, **kwargs)
    monkeypatch.setattr(SkillExecution, 'generate', generate)
    chat = AsyncMock(side_effect=AssertionError('Production must not enter the CRUD tool loop'))
    monkeypatch.setattr('services.creation_agent.handler.stream_creation_agent', chat)
    await AiTask.filter(id=task.id).update(status=6)
    await task.refresh_from_db()
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert task.response_data['plan_prepared'] is True
    assert await plan_proposal(task.id)
    assert await Scene.filter(chapter_id=request.chapter_id).count() == 1
    chat.assert_not_called()


@pytest.mark.asyncio
async def test_nonproduction_broad_request_falls_back_with_one_run_start(monkeypatch):
    from pydantic_ai.models.function import FunctionModel
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.handler import CreationAgentTaskHandler
    from services.creation_agent.event_log import agent_event_log
    from utils.enums import AiTaskTypeEnum
    _, _, _, task, _, _ = await plan_fixture()
    async def answer(messages, info):
        yield '本次无需修改。'
    monkeypatch.setattr(CreationPlanner, 'prepare', AsyncMock(return_value=None))
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=answer))
    await AiTask.filter(id=task.id).update(status=6)
    await task.refresh_from_db()
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    message = await AgentMessage.get(task=task, role='assistant')
    events = await agent_event_log.load(message)
    assert sum(event['type'] == 'RUN_STARTED' for event in events) == 1
    assert events[-1]['type'] == 'RUN_FINISHED'
