"""Model-directed pace, voice timeline structure and retry preservation."""
import json

import pytest

from prompts.skill_pack import ROOT, FILES, SkillSnapshot, instructions
from services.storyboard.speech_tracks import SpeechContent
from test.test_services.test_prompt_language import _shot


def snapshot(with_timing=True):
    contents = {name: (ROOT / filename).read_text() for name, filename in FILES.items()}
    if not with_timing:
        contract = json.loads(contents['storyboard_contract'])
        contract.pop('speech_baseline', None)
        contents['storyboard_contract'] = json.dumps(contract)
    return SkillSnapshot(revision='test', contents=contents)


def shot(text, field='dialogue', end=4, start=0):
    result = _shot()
    result.duration = f'{max(4, end)}s'
    setattr(result, field, [f'{start}s-{end}s: @{{李舟}}（平静）：{text}'])
    return result


def test_retry_can_split_but_cannot_delete_reword_or_change_speaker():
    validator = SpeechContent()
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


def test_malformed_entry_can_be_repaired_before_freezing_speech():
    validator = SpeechContent()
    with pytest.raises(ValueError, match='正文'):
        validator.validate([shot('')])
    validator.validate([shot('你好。', end=1)])


def test_frozen_baseline_is_visible_in_model_instructions():
    value = snapshot()
    contract = json.loads(value.read('storyboard_contract'))
    contract['speech_baseline']['characters_per_second'] = 3.2
    value.contents['storyboard_contract'] = json.dumps(contract)
    assert '"characters_per_second": 3.2' in instructions(value, 'zh', 'storyboard')
    assert '"speech_baseline"' not in instructions(snapshot(False), 'zh', 'storyboard')


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
        assert 'speech_baseline' in info.instructions
        if attempts == 1:
            shots = [candidate('你先回家。我们明天再见。', 3)]  # Overlap and the second track exceeds the shot.
        elif not repair:
            assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
            shots = [candidate('你先回家。', 1.5)]
        else:
            shots = [candidate('你先回家。', 1.5), candidate('我们明天再见。', 2)]
            shots[1]['sequence'] = 2
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'shots': shots})])

    model = FunctionModel(respond)
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


def shipped_snapshot():
    from prompts.skill_pack import snapshot_skills
    return SkillSnapshot.model_validate(snapshot_skills())


def timed_shot(number, name, text, end, cue='平静', field='dialogue'):
    candidate = shot(text, field, end=end)
    candidate.sequence = number
    setattr(candidate, field, [f'0s-{end}s: @{{{name}}}（{cue}）：{text}'])
    return candidate


@pytest.mark.parametrize("legacy_rates", [False, True])
def test_performance_tempo_alone_never_requests_a_repair_or_blocks_compilation(legacy_rates):
    from services.storyboard.candidates import StoryboardCandidateValidator
    from services.storyboard.validation import prepare_skill_storyboard
    from schemas.agent_workflow import StructuredSkillStoryboard

    text = '今天这件事我一定要问清楚。'
    shots = [timed_shot(1, '张正元', text, 3.5),
             timed_shot(2, '张正元', text, 1.2, '争执中抢话'),
             timed_shot(3, '张正元', '嘘，呵，呼，嘶，吹，嘻。', 9, '耐心教他念'),
             timed_shot(4, '张正元', text, 3.5)]
    snap = shipped_snapshot()
    if legacy_rates:
        contract = json.loads(snap.read('storyboard_contract'))
        contract.pop('speech_baseline')
        contract['speech_timing'] = {'characters_per_second': [2.5, 4.5], 'words_per_second': [1.5, 2.7],
                                     'pause_seconds': 0.2, 'slack_seconds': 0.5}
        snap.contents['storyboard_contract'] = json.dumps(contract)
    validator = StoryboardCandidateValidator(StructuredSkillStoryboard, snap, 'zh', [1, 30], {})
    raw = [s.model_dump(exclude={'prompt'}) for s in shots]
    board, checkpoint = validator.merge(validator.draft_type(shots=raw))
    assert board is not None and checkpoint['pending'] == {}
    ready = prepare_skill_storyboard(board, snap, 'zh', [], 'cinematic')
    assert [s.dialogue for s in ready.shots] == [s.dialogue for s in shots]
