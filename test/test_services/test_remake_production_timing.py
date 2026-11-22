import pytest
from scenedetect import FrameTimecode
from services.remake.production_timing import production_ranges, whole_second
from services.remake.scene_detection import SceneDetector
from services.remake.handoff import finalize_generation_shots
from services.remake.storyboards import prepare_remake_prompt
from test.remake_fixtures import remake_shot, synthetic_snapshot


@pytest.mark.parametrize('limit', [1, 5, 10, 15, 30])
def test_camera_cuts_stay_inside_integer_generation_budget(limit):
    edges = [FrameTimecode(n, 15) for n in (0,64,130,194,259,371)]
    groups = production_ranges(list(zip(edges,edges[1:])), limit)
    detector = SceneDetector(limit)
    detector.source_cuts = [p.get_seconds() for p in edges[1:-1]]
    spans = [detector.interval(a,b) for a,b in groups]
    assert all(1 <= s['output_seconds'] <= limit and isinstance(s['output_seconds'],int) for s in spans)
    assert sum(s['output_seconds'] for s in spans) == 25
    assert groups[0][0]==edges[0] and groups[-1][1]==edges[-1]
    assert all(a[1]==b[0] for a,b in zip(groups,groups[1:]))
    if limit==15:
        assert [s['output_seconds'] for s in spans] == [13,12]
        assert spans[0]['internal_cuts'] == [x.get_seconds() for x in edges[1:3]]


def test_short_source_and_unbroken_take_preserve_all_frames():
    for n in (1,6,52,302,1001):
        a,b=FrameTimecode(0,24),FrameTimecode(n,24)
        groups=production_ranges([(a,b)],3)
        durations=[SceneDetector(3).interval(x,y)['output_seconds'] for x,y in groups]
        assert sum(durations)==max(1,whole_second(n/24))
        assert max(durations)<=3 and min(durations)>=1


def test_completed_throw_is_excluded_but_a_distinct_repeat_and_the_catch_survive():
    def shot(i, start, end, secs):
        return {**remake_shot(i, refs=[]),'source_interval':{'start_seconds':start,'end_seconds':end,'output_seconds':secs}}
    a,b=shot(1,0,4.3,4),shot(2,4.3,8.8,5)
    a.update(actions=['1-3：抛出甜筒。','3-5：甜筒在空中旋转。'],transition='甜筒已离手，正在空中。')
    b.update(actions=['1-3：抛出甜筒。','3-5：甜筒在空中旋转。','5-6：女子接住甜筒。','7-8：抛出甜筒。'],
             visual_prose='甜筒已在女子面前。')
    x,y=finalize_generation_shots([a,b],'zh')
    assert (x['duration'],y['duration']) == ('4s','5s')
    assert len(y['actions'])==3 and sum('抛出甜筒。' in l for l in y['actions'])==1
    assert y['actions'][0].startswith('0s-') and y['actions'][0].endswith(b['visual_prose'])
    assert '女子接住甜筒' in y['actions'][1]
    assert 'handoff' not in y
    prompt=prepare_remake_prompt(y,[],synthetic_snapshot(),'zh')['prompt']
    assert a['transition'] not in prompt and prompt.count(y['actions'][1])==1
    assert '总时长：@{镜头时长:5s}' in prompt


def test_short_batch_uses_integer_plan_without_rounding_internal_timestamps():
    from schemas.remake_short import RemakeShortStoryboard
    from test.test_services.test_remake_short_storyboard import sample
    span = {'sequence':1, 'start_seconds':0, 'end_seconds':4.4, 'output_seconds':4,'internal_cuts':[1.65]}
    rendered = RemakeShortStoryboard.model_validate(sample(1)).materialize([span])[1]
    rendered.update(shot_index=1, source_interval=span, actions=['0–1.65：手持甜筒。','1.65–4.4：递出甜筒。'])
    shot, = finalize_generation_shots([rendered],'zh')
    assert shot['duration']=='4s' and shot['internal_cut_seconds']==[1.5]
    assert shot['actions']==['0s-1.5s: 手持甜筒。','1.5s-4s: 递出甜筒。']


@pytest.mark.asyncio
async def test_remote_worker_receives_frozen_shot_limit(tmp_path):
    from unittest.mock import AsyncMock
    from services.remake.remote_media import RemoteMediaSession, MediaWorkerConnection, RemoteMediaError
    remote = RemoteMediaSession(MediaWorkerConnection(host='host',root='/worker'))
    remote._command = AsyncMock(return_value='{"scenes":[]}')
    with pytest.raises(RemoteMediaError):
        await remote.split(tmp_path,timeline=True,shot_limit=12)
    remote._command.assert_not_called()
    remote.timeline_available = remote.production_ranges_available = True
    # A deliberately empty manifest fails protocol validation after argument forwarding.
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        await remote.split(tmp_path,timeline=True,shot_limit=12)
    remote._command.assert_awaited_once_with('split_timeline',shot_limit=12)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_old_shot_with_saved_memory_renders_only_current_content(language):
    raw = {**remake_shot(2, refs=[]), "generation_timeline": True,
           "visual_prose": "On the beach, an airplane passes the sign.",
           "handoff": {"end_state": "PREVIOUS_SHOT_CONTENT"}}
    result = prepare_remake_prompt(raw, [], synthetic_snapshot(), language)
    assert raw["visual_prose"] in result["prompt"]
    assert "PREVIOUS_SHOT_CONTENT" not in result["prompt"]
