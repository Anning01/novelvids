from test.agent_stream_fixtures import streaming_model
import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from schemas.agent_workflow import StructuredSkillStoryboard
from services.storyboard.candidates import StoryboardCandidateValidator
from test.test_services.test_prompt_language import _shot
from test.test_services.test_storyboard_speech_timing import snapshot


def raw_shot(number, **changes):
    return {**_shot().model_dump(exclude={'prompt'}), 'actions': ['0s-4s: Rain falls.'], 'sequence': number, **changes}


def test_split_retains_other_shots_and_freezes_original_speech():
    validator = StoryboardCandidateValidator(StructuredSkillStoryboard, snapshot(), 'zh', [1, 4], {})
    first = raw_shot(1, description='keep-first')
    third = raw_shot(3, description='keep-third')
    bad = raw_shot(2, narration=['0s-5s: 旁白：你先回家。我们明天再见。'])
    output, state = validator.merge(validator.draft_type(shots=[first, bad, third]))
    assert output is None and state['accepted_shots'] == [1, 3]
    shortened = raw_shot(2, repair_of=2, narration=['0s-1.5s: 旁白：你先回家。'])
    output, state = validator.merge(validator.draft_type(shots=[shortened]))
    assert output is None and 2 in state['pending']
    # Recovery keeps the original speech and valid slots, not the shortened attempt.
    recovered = StoryboardCandidateValidator(StructuredSkillStoryboard, snapshot(), 'zh', [1, 4], {})
    recovered.restore(json.loads(json.dumps(state)))
    validator = recovered
    output, state = validator.merge(validator.draft_type(shots=[shortened,
        raw_shot(2, repair_of=2, narration=['0s-2s: 旁白：我们明天再见。'])]))
    assert not state['pending']
    assert [s.sequence for s in output.shots] == [1, 2, 3, 4]
    assert output.shots[0].description == 'keep-first'
    assert output.shots[3].description == 'keep-third'


def test_retry_compaction_keeps_complete_targeted_instructions():
    from services.creation_agent.history import compact_retry_history
    text = 'repair only shot 2: ' + 'keep exact speech ' * 200
    messages = [ModelResponse(parts=[ToolCallPart('output', {'shots': ['huge full chapter']}, tool_call_id='shot-call')]),
        ModelRequest(parts=[RetryPromptPart(text, tool_name='output', tool_call_id='shot-call')])]
    compacted = compact_retry_history(messages)
    assert compacted[-1].parts[0].content == text
    assert 'huge full chapter' not in str(compacted[0].parts[0].args)


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('failure', ['schema', 'timing', 'reference', 'malformed_reference'])
async def test_actual_model_retry_requests_only_invalid_shot_and_saves_all_others(language, failure):
    from controllers.scene import scene_controller
    from models.scene import Scene
    from models.agent_operation import AgentOperation
    from models.config import GeneralConfig
    from services.ai_task_executor import ai_task_executor
    from test.test_services.test_skill_workflow import enabled_project

    _, chapter, _ = await enabled_project()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': language})
    first = raw_shot(1, description='keep-first')
    third = raw_shot(3, description='keep-third')
    bad = raw_shot(2)
    if failure == 'schema':bad.pop('environment')
    elif failure == 'timing':bad['actions'] = ['0s-99s: Rain falls.']
    elif failure == 'reference':bad['visual_prose'] = '@{MissingIdentity} enters.'
    else:bad['visual_prose'] = '@MissingIdentity enters.'
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            shots = [first, bad, third]
        else:
            retry = next(part.content for message in reversed(messages) for part in message.parts if isinstance(part, RetryPromptPart))
            assert 'repair_of' in retry and 'repair_targets' in retry
            assert 'keep-first' not in retry and 'keep-third' not in retry
            shots = [raw_shot(2, repair_of=2), raw_shot(1, repair_of=1, description='unwanted rewrite')]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'shots': shots})])
    model = streaming_model(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await scene_controller.generate(chapter.id)
        task.request_params['skill_snapshot'] = snapshot(False).model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert calls == 2
    shots = await Scene.filter(chapter=chapter).order_by('sequence')
    assert len(shots) == 3
    assert shots[0].description == 'keep-first' and shots[2].description == 'keep-third'
    checkpoint = await AgentOperation.get(task=task, key='candidate:storyboard:')
    assert checkpoint.result['pending'] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('localized', [True, False])
async def test_semantic_check_never_requests_a_full_chapter_rewrite(localized):
    from schemas.creation_plan import CreationStepContext, CreativeCheck
    from services.creation_agent.creative_checks import generate_checked
    from test.test_services.test_creation_plans import confirmed_fixture
    _, _, plan, _, execution = await confirmed_fixture()
    context = CreationStepContext(step=plan.steps[0], original_message='生成分镜', requirements=plan.brief.requirements, sources=plan.excerpts)
    candidate = StructuredSkillStoryboard.model_validate({'shots': [raw_shot(1, description='keep-first'), raw_shot(2), raw_shot(3, description='keep-third')]})
    calls = []
    async def generate(skill, facts, output_type, **options):
        calls.append(skill)
        if skill == 'creative_check':
            return CreativeCheck(plan_followed=False, issues=['Missing dialogue'], findings=[{
                'requirement_id': 'opening', 'passed': False, 'location': 'shot 2' if localized else 'global',
                'detail': 'Missing dialogue', 'shot_sequences': [2] if localized else []}])
        if 'storyboard_repair' in facts:
            assert [shot['sequence'] for shot in facts['repair_targets']] == [2]
            assert 'candidate' not in facts
            merger = StoryboardCandidateValidator(output_type, snapshot(False), 'zh', [1, 30], facts)
            merged, _ = merger.merge(merger.draft_type(shots=[raw_shot(2, repair_of=2, description='fixed'),
                raw_shot(1, repair_of=1, description='unwanted rewrite')]))
            assert merged.shots[0].description == 'keep-first'
            return merged
        return candidate
    with patch.object(execution, '_generate', side_effect=generate):
        result = await generate_checked(execution, 'storyboard', {}, StructuredSkillStoryboard, {}, context)
    assert result.shots[0].description == 'keep-first' and result.shots[2].description == 'keep-third'
    assert calls.count('storyboard') == (2 if localized else 1)
