from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from schemas.remake import RemakeSpeechEvidence
from services.remake.speech_boundary import apply_speech_evidence, repeated_lines, review_speech, speech_text


def shot(line, **kwargs):
    return {'dialogue':[f'0s-2s: @角色甲（平静）：{line}'], 'narration':[], 'actions':['她拿起杯子。'], **kwargs}


@pytest.mark.asyncio
async def test_only_a_verified_split_changes_spoken_words_and_preserves_original_shots(tmp_path):
    text = '雨停之前先合上这把伞'
    inputs = [shot(text, description=f'她说“{text}”'), shot(text), shot('我知道')]
    model = SimpleNamespace(analyze_one=AsyncMock(side_effect=[
        {'certain':True,'words':'雨停之前'},{'certain':True,'words':'先合上这把伞'}]))
    paths = [tmp_path/f'{i}.mp4' for i in range(3)]
    shots, reviews = await review_speech(inputs,paths,model,{},'zh')
    assert reviews == [{'previous':1,'current':2,'field':'dialogue','decision':'split_at_cut'}]
    assert speech_text(shots[0]['dialogue'][0])[1] == '雨停之前'
    assert shots[1]['dialogue'] == ['0s-2s: @角色甲（平静）：先合上这把伞']
    assert shots[0]['description'] == '她说“雨停之前”'
    assert inputs[0]['dialogue'][0].endswith(text) and shots[2] == inputs[2]
    assert [c.kwargs['path'] for c in model.analyze_one.await_args_list] == paths[:2]


@pytest.mark.parametrize('left,right,certain,outcome', [('拿起杯子','拿起杯子',True,'source_repetition'),
    ('拿起','杯子',False,'unresolved'),('他','杯子',True,'unresolved'),('拿起杯子','',True,'split_at_cut')])
def test_replay_and_uncertain_audio_are_not_removed(left,right,certain,outcome):
    a,b=shot('拿起杯子'),shot('拿起杯子')
    evidence=lambda words:RemakeSpeechEvidence(words=words,certain=certain)
    assert apply_speech_evidence(a,b,'dialogue',evidence(left),evidence(right)) == outcome
    if outcome != 'split_at_cut': assert a['dialogue'] == b['dialogue']
    else: assert b['dialogue'] == []
    assert b['actions'] == ['她拿起杯子。']


def test_state_continuity_without_repeated_dialogue_is_not_a_model_call():
    assert not list(repeated_lines(shot('上车吧'),shot('车在等你')))
