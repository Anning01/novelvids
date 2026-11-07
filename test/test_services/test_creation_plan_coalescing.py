from unittest.mock import AsyncMock, patch

import pytest

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.creation_agent import AgentMessage, AgentConversation
from schemas.creation_plan import CreationPlanStep, CreationStepContext, CreativeCheck
from schemas.agent_workflow import CompletePrompt
from services.creation_agent.plan_normalization import coalesce_storyboards, execution_plan
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.plans import load_plan
from services.creation_agent.plan_execution import CreationPlanRunner
from services.creation_agent.skill_execution import current_execution
from services.creation_agent.step_context import step_context
from services.creation_agent.waiting import WaitingForDependencies
from test.test_services.test_creation_plans import confirmed_fixture


def section(identifier, target=1, **kwargs):
    return CreationPlanStep(id=identifier, operation='storyboard', target_id=target,
        label=identifier, instructions=f'{identifier} 的叙事内容', **kwargs)


def test_four_sections_become_one_complete_chapter_in_order():
    steps = [section(name, requirement_ids=[name]) for name in ['opening', 'reality', 'backstory', 'ending']]
    merged, groups = coalesce_storyboards(steps, {1: 1})
    assert len(merged) == 1
    assert groups == {'opening': ['opening', 'reality', 'backstory', 'ending']}
    assert merged[0].requirement_ids == ['opening', 'reality', 'backstory', 'ending']
    assert '完整' in merged[0].label
    assert [merged[0].instructions.index(step.instructions) for step in steps] == sorted(merged[0].instructions.index(step.instructions) for step in steps)
    assert steps[0].instructions == 'opening 的叙事内容'


def test_dependencies_and_output_references_follow_the_single_chapter_job():
    a = CreationPlanStep(id='assets1', operation='assets', target_id=1, label='资产', instructions='提取')
    b = a.model_copy(update={'id': 'assets2', 'target_id': 2})
    video = CreationPlanStep(id='video', operation='video', source_step='ending', depends_on=['ending'], label='视频', instructions='生成')
    steps = [a, section('opening', depends_on=['assets1']), b, section('ending', depends_on=['assets2']), video]
    merged, _ = coalesce_storyboards(steps, {1: 1})
    assert [step.id for step in merged] == ['assets1', 'assets2', 'opening', 'video']
    assert merged[2].depends_on == ['assets1', 'assets2']
    assert merged[3].source_step == 'opening' and merged[3].depends_on == ['opening']


def test_conflicting_replacement_modes_are_not_silently_combined():
    with pytest.raises(ValueError, match='不同处理方式'):
        coalesce_storyboards([section('a'), section('b', mode='revise')], {1: 1})


def test_coalescing_cannot_erase_an_external_dependency_cycle():
    video = CreationPlanStep(id='video', operation='video', source_step='a', depends_on=['a'], label='视频', instructions='生成')
    with pytest.raises(ValueError, match='循环依赖'):
        coalesce_storyboards([section('a'), video, section('b', depends_on=['video'])], {1: 1})


@pytest.mark.asyncio
async def test_old_confirmed_sections_submit_one_job_without_mutating_approval():
    _, _, plan, root, execution = await confirmed_fixture()
    original = plan.steps[0]
    plan.steps = [original.model_copy(update={'id': name, 'label': name, 'instructions': f'{name}内容'})
                  for name in ['opening', 'reality', 'backstory', 'ending']]
    snapshot = plan.model_dump(mode='json')
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=snapshot)
    captured = []
    async def submit(intent, **kwargs):
        parent = current_execution.get()
        context = await step_context(parent.params)
        assert context.coalesced_step_ids == ['opening', 'reality', 'backstory', 'ending']
        assert all(name + '内容' in context.step.instructions for name in context.coalesced_step_ids)
        child = await AiTask.create(task_type=3, status=6, request_params=parent.params)
        await AgentOperation.create(task=root, key='submit:' + str(intent.request_id), state='completed', result={'task_id': str(child.id)})
        captured.append(child)
        return {'task_id': str(child.id)}
    with patch('services.creation_agent.plan_execution.submit_intent', side_effect=submit) as submitter:
        with pytest.raises(WaitingForDependencies):
            await CreationPlanRunner(execution).run()
        assert submitter.await_count == 1
        projected, _ = execution_plan(plan, execution.language)
        await AgentOperation.create(task=captured[0], key='coalesced:validated', state='completed',
            result={'revision': fingerprint(projected.steps[0].model_dump())[:20]})
        await AiTask.filter(id=captured[0].id).update(status=3, response_data={'scene_ids': []})
        result = await CreationPlanRunner(execution).run()
    assert len(result['steps']) == 1 and not result['partial']
    assert (await load_plan(execution.params['creation_plan_id'])).model_dump(mode='json') == snapshot


@pytest.mark.asyncio
async def test_partial_candidate_is_reused_then_repaired_against_all_sections():
    from services.creation_agent.creative_checks import generate_checked
    _, _, plan, task, execution = await confirmed_fixture()
    context = CreationStepContext(step=plan.steps[0], original_message='生成完整第一章', requirements=plan.brief.requirements,
        sources=plan.excerpts, coalesced_step_ids=['opening', 'ending'])
    await AgentOperation.create(task=task, key='model:video:CompletePrompt:', state='completed', external=True,
        result={'prompt': '仅开场候选'})
    calls = []
    async def generate(skill, facts, output_type, **kwargs):
        calls.append(skill)
        if skill == 'creative_check':
            passed = facts['candidate']['prompt'] == '完整章节候选'
            return CreativeCheck(plan_followed=passed, findings=[{'requirement_id': 'opening', 'passed': passed,
                'location': 'prompt', 'detail': '检查整章覆盖'}], issues=[] if passed else ['缺少后续段落'])
        assert facts['candidate']['prompt'] == '仅开场候选'
        return CompletePrompt(prompt='完整章节候选')
    with patch.object(execution, '_generate', side_effect=generate):
        result = await generate_checked(execution, 'video', {}, CompletePrompt, {}, context)
    assert result.prompt == '完整章节候选'
    assert calls == ['creative_check', 'video', 'creative_check']
    assert await AgentOperation.filter(task=task, key='coalesced:validated', state='completed').exists()


@pytest.mark.asyncio
async def test_execution_usage_includes_private_production_children():
    from services.creation_agent.receipts import usage_summary
    _, _, _, root, execution = await confirmed_fixture()
    await AgentMessage.filter(id=execution.message.id).update(run_input={'creation_run_id': str(root.id)})
    private = await AgentConversation.create(novel_id=execution.params['novel_id'])
    production = await AiTask.create(task_type=3, status=3, request_params={'creation_run_id': str(root.id)})
    model = await AiTask.create(task_type=7, status=3,
        request_params={'creation_run_id': str(root.id), 'parent_task_id': str(production.id)})
    await AgentMessage.create(conversation=private, task=production, role='assistant', request_id=production.id, request_hash='parent')
    await AgentMessage.create(conversation=private, task=model, role='assistant', request_id=model.id, request_hash='model',
        usage={'requests': 3, 'input_tokens': 120, 'output_tokens': 30})
    await AgentOperation.create(task=root, key='submit:production', state='completed', result={'task_id': str(production.id)})
    message = await AgentMessage.get(id=execution.message.id)
    result = await usage_summary(message)
    assert result['requests'] == 3 and result['input_tokens'] == 120 and result['output_tokens'] == 30


@pytest.mark.asyncio
async def test_coalesced_activity_keeps_the_real_chapter_failure_visible():
    from services.creation_agent.activity import activity_for_messages
    _, _, _, root, execution = await confirmed_fixture()
    await AgentMessage.filter(id=execution.message.id).update(run_input={'creation_run_id': str(root.id)})
    message = await AgentMessage.get(id=execution.message.id).select_related('task')
    await AgentOperation.create(task=root, key='plan:coalesced', state='completed', result={'groups': {'opening': ['opening', 'ending']}})
    events = [{'type': 'CUSTOM', 'name': 'agent_activity', 'value': {'id': f'creation:step:{key}',
        'kind': 'status', 'label': key, 'status': 'failed'}} for key in ['opening', 'ending']]
    result = await activity_for_messages([message], {message.id: events}, {})
    steps = result[message.id]
    assert [step['id'] for step in steps] == ['creation:step:opening']
    assert steps[0]['status'] == 'failed'
