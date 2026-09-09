import copy
import json
from collections import Counter

import pytest
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import FunctionModel, DeltaToolCall

from test.creation_agent_evaluation import CORPUS_PATH, load_cases, create_evaluation_project, business_snapshot, evaluate_invariants, run_evaluation_case
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum


def test_fixed_corpus_has_thirty_cases_and_all_requested_categories():
    cases = load_cases()
    assert len(cases) == len({case.id for case in cases}) == 30
    assert Counter(case.group for case in cases) == {'image': 10, 'storyboard': 10, 'scope': 10}
    assert json.loads(CORPUS_PATH.read_text())['repetitions'] == 3
    assert any(step.new_conversation for case in cases for step in case.steps)
    assert {step.chapter for case in cases for step in case.steps} == {1, 2, 3}
    assert {'clarify', 'refuse', 'memory', 'edit'} == {step.expected_outcome for case in cases for step in case.steps}


@pytest.mark.asyncio
async def test_fixture_preserves_twelve_independent_scenes_and_chapter_three_variant():
    novel, chapters, targets = await create_evaluation_project(load_cases()[0])
    snapshot = await business_snapshot(novel.id)
    assert len(chapters) == 3 and len(snapshot['scene']) == 12
    assert len(snapshot['asset']) == 4 and len(snapshot['variant']) == 1
    assert snapshot['variant'][0]['chapter_numbers'] == [3]
    assert len({targets[label] for label in 'ABCDEFGHIJKL'}) == 12
    assert all(row['duration'] == 6 and row['asset_ids'] for row in snapshot['scene'])


@pytest.mark.asyncio
async def test_model_context_keeps_structured_facts_and_preserves_manual_or_empty_text():
    from uuid import uuid4
    from models.scene import Scene
    from services.creation_agent.tools import PromptEditService
    novel, _, targets = await create_evaluation_project(load_cases()[0])
    service = PromptEditService(novel_id=novel.id, task_id=uuid4(), allowed_targets={targets['A'], targets['B']}, max_batch_size=8)
    full = await service.read_targets()
    compact = await service.read_targets(for_model=True)
    for before, after in zip(full, compact):
        assert after['edit_mode'] == 'changes' and 'prompt' not in after
        assert all(before[key] == after[key] for key in ('version', 'prompt_params', 'entities', 'duration'))
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False))
    await Scene.filter(id=targets['A'][1]).update(prompt=None, prompt_params={})
    await Scene.filter(id=targets['B'][1]).update(prompt='用户最新手工构图，不得被旧参数覆盖。')
    texts = await service.read_targets(for_model=True)
    assert all(row['edit_mode'] == 'legacy_prompt' for row in texts)
    assert texts[0]['prompt'] is None
    assert texts[1]['prompt'] == '用户最新手工构图，不得被旧参数覆盖。'


def test_invariant_checker_catches_unauthorized_changes_even_if_reply_claims_success():
    before = {'novel': [{'id': 1, 'name': '原名称'}], 'scene': [{'id': 4, 'sequence': 4, 'duration': 6,
        'prompt': '旧提示词', 'prompt_params': {'visual_prose': '旧画面', 'dialogue': ['不许改台词']}}]}
    after = copy.deepcopy(before)
    after['scene'][0]['prompt'] = '【镜头4 · 0s-2s】镜头1的女生'
    after['scene'][0]['prompt_params']['dialogue'] = []
    after['novel'][0]['name'] = '越权新名称'
    failures = evaluate_invariants(before, after, {('scene', 4)}, {4: 3})
    assert 'novel:1: protected fields changed' in failures
    assert 'scene:4: protected fields changed' in failures
    assert 'scene:4: external shorthand' in failures
    assert 'scene:4: nonlocal numbering' in failures
    assert 'scene:4: incorrect segment count' in failures
    assert before['scene'][0]['prompt_params']['visual_prose'] == '旧画面'


def test_invariant_checker_does_not_blame_unchanged_legacy_text_on_a_failed_edit():
    before = {'novel': [], 'chapter': [], 'asset': [], 'variant': [], 'scene': [{
        'id': 4, 'prompt': '镜头4的女生，服装同上', 'prompt_params': {}, 'duration': 6,
    }]}
    after = copy.deepcopy(before)
    assert evaluate_invariants(before, after, {('scene', 4)}, {4: 3}) == []


def test_definition_checker_accepts_reference_markup_but_rejects_missing_traits():
    from test.creation_agent_evaluation import missing_current_definitions
    target = {'prompt': '场景概念图：@{站台}。旧@{站台}，灰色地面，绿色指示牌。',
              'entities': [{'name': '站台', 'description': '旧站台，灰色地面，绿色指示牌。'}]}
    assert missing_current_definitions(target) == []
    target['prompt'] = '场景概念图：@{站台}。旧@{站台}，灰色地面。'
    assert missing_current_definitions(target) == ['站台']


@pytest.mark.asyncio
async def test_evaluation_runs_actual_tasks_and_leaves_quality_unreviewed(monkeypatch, tmp_path):
    config = await AiModelConfig.create(task_type=AiTaskTypeEnum.creation_agent.value, name='evaluation-test',
        model='function-model', base_url='https://example.invalid/v1', api_key='synthetic-key',
        supports_tool_calls=True, is_active=True, pricing={'type': 'text', 'input_price_per_1m': 1, 'output_price_per_1m': 1})
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {0: DeltaToolCall(name='get_creation_context', json_args='{}', tool_call_id='read')}
        elif calls == 2:
            context = next(part.content for message in messages for part in message.parts if isinstance(part, ToolReturnPart))
            target = context['targets'][0]
            yield {0: DeltaToolCall(name='update_image_prompt', tool_call_id='write', json_args=json.dumps({'edits': [{
                'target_kind': target['kind'], 'target_id': target['id'],
                'prompt': target['prompt'] + '窗边柔和自然光。',
            }]}, ensure_ascii=False))}
        else:
            yield '已保存人物的窗边柔光设定。'

    from test.creation_agent_evaluation_budget import EvaluationSpendLedger, BudgetedEvaluationModel
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', {**config.pricing, 'currency': 'CNY'})
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: BudgetedEvaluationModel(FunctionModel(stream_function=model), ledger))
    result = await run_evaluation_case(load_cases()[0], config, 1)
    assert result['status'] == 'awaiting_quality_review'
    step = result['steps'][0]
    assert step['changes'] and not step['hard_failures']
    assert step['usage']['requests'] == 3
    entries = [json.loads(line) for line in ledger.path.read_text().splitlines()]
    assert len(entries) == 6 and entries[-1]['status'] == 'settled'
    assert step['first_event_seconds'] is not None
    assert step['duration_seconds'] >= step['first_event_seconds']
    assert step['quality_review']['reviewer'] is None
    assert step['quality_review']['intent'] is None
    assert 'synthetic-key' not in json.dumps(result, ensure_ascii=False, default=str)


def test_report_never_turns_missing_runs_or_reviews_into_a_pass():
    from test.creation_agent_evaluation_report import summarize
    report = summarize([])
    assert report['status'] == 'incomplete_or_failed'
    assert report['unique_instances'] == 0 and report['planned_instances'] == 90
    assert report['quality_means']['intent'] is None
    assert any('quality review' in reason for reason in report['reasons'])


def test_report_distinguishes_authorized_reservation_from_measured_usage():
    from test.creation_agent_evaluation_report import summarize
    report = summarize([], [
        {'id': 'first', 'status': 'unknown', 'cost_cny': '0.211230'},
        {'id': 'first', 'status': 'settled', 'cost_cny': '0.211230',
         'cost_basis': 'user_authorized_full_reservation'},
        {'id': 'next', 'status': 'settled', 'cost_cny': '0.1'},
    ])
    assert report['cumulative_spend_cny'] == '0.311230'
    assert report['authorized_reservation_cny'] == '0.211230'
    assert report['status'] == 'incomplete_or_failed'  # No quality evidence fabricated.


def test_report_keeps_all_attempts_and_requires_ninety_independently_reviewed_instances():
    import hashlib
    from test.creation_agent_evaluation_report import summarize
    records = []
    for case in load_cases():
        for repetition in (1, 2, 3):
            records.append({'case_id': case.id, 'repetition': repetition, 'model': 'synthetic-report-fixture',
                'corpus_sha256': hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest(),
                'steps': [{'hard_failures': [], 'outcome_failures': [], 'cost_cny': '0', 'usage': {},
                    'quality_review': {'reviewer': '测试评审者', 'reason': '仅验证报告聚合逻辑，不是真实模型结果',
                        'intent_fulfilled': True, 'intent': 4, 'continuity': 4, 'independent_use': 4}}
                    for _ in case.steps]})
    assert summarize(records, [])['status'] == 'ready_for_final_review'
    duplicate = summarize([*records, records[0]], [])
    assert duplicate['status'] == 'incomplete_or_failed'
    assert duplicate['recorded_attempts'] == 91
    records[0]['steps'][0]['quality_review']['reviewer'] = None
    assert summarize(records, [])['status'] == 'incomplete_or_failed'
