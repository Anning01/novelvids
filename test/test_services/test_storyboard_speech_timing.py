"""Speech budgets, retry preservation, and historical snapshot compatibility."""
from test.agent_stream_fixtures import streaming_model
import json

import pytest
from pydantic import ValidationError

from prompts.skill_pack import ROOT, FILES, SkillSnapshot, instructions
from services.storyboard.speech_timing import StoryboardSpeechValidator
from test.test_services.test_prompt_language import _shot


POLICY = {
    'characters_per_second': [2.5, 4.5],
    'words_per_second': [1.5, 2.7],
    'pause_seconds': 0.2,
    'slack_seconds': 0.5,
}


def snapshot(with_timing=True):
    contents = {name: (ROOT / filename).read_text() for name, filename in FILES.items()}
    contract = json.loads(contents['storyboard_contract'])
    if with_timing:
        contract['speech_timing'] = POLICY
    else:
        contract.pop('speech_timing', None)
    contents['storyboard_contract'] = json.dumps(contract)
    return SkillSnapshot(revision='test', contents=contents)


def shot(text, field='dialogue', end=4, start=0):
    result = _shot()
    result.duration = f'{max(4, end)}s'
    setattr(result, field, [f'{start}s-{end}s: @{{李舟}}（平静）：{text}'])
    return result


@pytest.mark.parametrize('field', ['dialogue', 'narration'])
def test_overfull_speech_rejected_without_mutation(field):
    candidate = shot('我今天来到这里就是为了把所有事情都告诉你。', field, end=2)
    before = candidate.model_dump()
    with pytest.raises(ValueError, match='拆成连续独立镜头'):
        StoryboardSpeechValidator(snapshot()).validate([candidate])
    assert candidate.model_dump() == before


@pytest.mark.parametrize('field', ['dialogue', 'narration'])
def test_slow_speech_requires_shorter_voice_window_not_faster_playback(field):
    with pytest.raises(ValueError, match='留白'):
        StoryboardSpeechValidator(snapshot()).validate([shot('你好。', field)])


def test_snapshots_without_timing_policy_keep_historical_behavior():
    validator = StoryboardSpeechValidator(snapshot(False))
    validator.validate([shot('很长的一段台词' * 10, end=1)])
    old = snapshot(False)
    old.contents.pop('storyboard_contract')
    StoryboardSpeechValidator(old).validate([shot('你好。')])


def test_retry_can_split_but_cannot_delete_reword_or_change_speaker():
    validator = StoryboardSpeechValidator(snapshot())
    with pytest.raises(ValueError):
        validator.validate([shot('你先回家。我们明天再见。', end=1)])
    for revised in ([shot('你先回家。', end=1.5)], [shot('你快回家。我们明天再见。')]):
        with pytest.raises(ValueError, match='完整保留'):
            validator.validate(revised)
    first, second = shot('你先回家。', end=1.5), shot('我们明天再见。', end=2)
    changed = second.model_copy(deep=True)
    changed.dialogue = [changed.dialogue[0].replace('李舟', '其他人')]
    with pytest.raises(ValueError, match='完整保留'):
        validator.validate([first, changed])
    validator.validate([first, second])


def test_mixed_text_numbers_pauses_and_speaker_metadata():
    validator = StoryboardSpeechValidator(snapshot())
    validator.validate([shot('你好，Alex。', end=2)])
    with pytest.raises(ValueError):
        validator.validate_shot(shot('编号1234567890。', end=1))
    validator.validate_shot(shot('你好。', end=1))
    validator.validate_shot(shot('Hello my old friend.', end=2))


def test_missing_speech_cannot_bypass_budget():
    candidate = shot('')
    with pytest.raises(ValueError, match='正文'):
        StoryboardSpeechValidator(snapshot()).validate_shot(candidate)


def test_malformed_entry_can_be_repaired_before_freezing_speech():
    validator = StoryboardSpeechValidator(snapshot())
    with pytest.raises(ValueError, match='正文'):
        validator.validate([shot('')])
    validator.validate([shot('你好。', end=1)])


def test_speech_budget_is_checked_before_compilation_and_on_saved_prompt_validation():
    from schemas.agent_workflow import StructuredSkillStoryboard
    from prompts.storyboard import format_storyboard_prompt
    from services.storyboard.validation import prepare_skill_storyboard, validate_skill_storyboard_shot

    candidate = shot('我今天来到这里就是为了把所有事情都告诉你。', end=2)
    candidate.prompt = format_storyboard_prompt(candidate, 'zh')
    with pytest.raises(ValueError, match='时间不足'):
        validate_skill_storyboard_shot(candidate, snapshot(), 'zh')
    raw = StructuredSkillStoryboard.model_validate({'shots': [candidate.model_dump(exclude={'prompt'})]})
    with pytest.raises(ValueError, match='时间不足'):
        prepare_skill_storyboard(raw, snapshot(), 'zh', [], 'narration')


def test_invalid_policy_is_rejected():
    value = snapshot()
    value.contents['storyboard_contract'] = json.dumps({'speech_timing': {**POLICY, 'characters_per_second': [4, 0]}})
    with pytest.raises(ValidationError):
        StoryboardSpeechValidator(value)


def test_policy_is_visible_in_model_instructions_and_snapshot_is_frozen():
    value = snapshot()
    assert 'speech_timing' in instructions(value, 'zh', 'storyboard')
    assert '"speech_timing"' not in instructions(snapshot(False), 'zh', 'storyboard')
    validator = StoryboardSpeechValidator(value)
    value.contents['storyboard_contract'] = '{}'
    with pytest.raises(ValueError):
        validator.validate([shot('你好。')])


@pytest.mark.asyncio
@pytest.mark.parametrize('repair', [True, False])
async def test_generation_retries_split_both_tracks_and_never_saves_deleted_speech(repair):
    from unittest.mock import AsyncMock, patch
    from pydantic_ai.messages import ModelResponse, ToolCallPart, RetryPromptPart
    from pydantic_ai.models.function import FunctionModel
    from controllers.scene import scene_controller
    from models.scene import Scene
    from services.ai_task_executor import ai_task_executor
    from test.test_services.test_skill_workflow import enabled_project

    _, chapter, _ = await enabled_project()
    old = await Scene.create(chapter=chapter, sequence=1, prompt='Keep original', duration=4)
    attempts = 0

    def candidate(text, end):
        value = _shot()
        value.actions = ['0s-4s: Rain falls.']
        value.narration = [f'0s-{end}s: 旁白：{text}']
        value.dialogue = [f'2s-{2 + end}s: 路人：{text}']
        return value.model_dump(exclude={'prompt'})

    def respond(messages, info):
        nonlocal attempts
        attempts += 1
        assert 'speech_timing' in info.instructions
        if attempts == 1:
            shots = [candidate('你先回家。我们明天再见。', .5)]
        elif not repair:
            assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
            shots = [candidate('你先回家。', 1.5)]
        else:
            shots = [candidate('你先回家。', 1.5), candidate('我们明天再见。', 2)]
            shots[1]['sequence'] = 2
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'shots': shots})])

    model = streaming_model(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await scene_controller.generate(chapter.id, replace_existing=True)
        task.request_params['skill_snapshot'] = snapshot().model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert attempts == 2  # The shared budget permits one repair, never a third paid call.
    if repair:
        assert task.status == 3, task.error_message
        saved = await Scene.filter(chapter=chapter).order_by('sequence')
        assert len(saved) == 2
        for field in ('narration', 'dialogue'):
            spoken = ''.join(line.split('：', 1)[1] for scene in saved for line in scene.prompt_params[field])
            assert spoken == '你先回家。我们明天再见。'
    else:
        assert task.status == 4
        assert (await Scene.get(id=old.id)).prompt == 'Keep original'
        assert await Scene.filter(chapter=chapter).count() == 1
