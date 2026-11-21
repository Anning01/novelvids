import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.remake.deadline import batch_deadline
from services.remake.single_wave import analyze_source_shots, bind_shot_references


def test_deadline_counts_upload_time_across_the_entire_batch(monkeypatch):
    monkeypatch.setattr('services.remake.deadline.time', lambda: 180.0)
    sources = [{'upload': SimpleNamespace(created_at=datetime.fromtimestamp(t, timezone.utc))} for t in (130, 100, 115)]
    assert batch_deadline(sources) == 400
    assert batch_deadline([{'upload': None}]) == 480


def test_reference_ids_are_local_and_ambiguous_names_require_review():
    assets = {'objects': [{'id': 'a', 'name': '快递盒', 'source_names': ['纸盒']},
                          {'id': 'b', 'name': '另一个盒子', 'aliases': ['盒子']},
                          {'id': 'c', 'name': '桌上的盒子', 'aliases': ['盒子']}]}
    one = {'asset_id': '01', 'asset_name': '纸盒', 'asset_type': 'object'}
    other = {**one, 'asset_name': '盒子'}
    unmapped = {**one, 'asset_type': 'character'}
    shots = bind_shot_references([{'asset_refs': [one]}, {'asset_refs': [other, unmapped]}], assets)
    assert shots[0]['asset_refs'] == [{**one, 'asset_id': 'a', 'asset_name': '快递盒'}]
    assert shots[1]['asset_refs'] == [] and shots[1]['unresolved_asset_refs'] == [other, unmapped]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 100])
async def test_single_wave_fills_the_selected_model_limit_and_never_rewrites(tmp_path, monkeypatch, limit):
    from models.ai_task import AiTask
    from services.creation_agent.skill_execution import current_execution
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from test.test_services.test_remake_gateway import _config, _Client
    gateway = RemakeVideoAnalysisGateway(_config(id=57, concurrency=limit), client=_Client([]))
    release = asyncio.Event()
    count = active = peak = 0

    async def request(**kw):
        nonlocal count, active, peak
        active += 1
        peak = max(peak, active)
        count += 1
        if active == limit:
            release.set()
        try:
            await asyncio.wait_for(release.wait(), 3)
            await asyncio.sleep(.001)
            assert kw['schema_name'] == 'professional_video_prompt_material' and not kw['draft']
            return {'shot_index': kw['index'], 'file': kw['path'].name}
        finally:
            active -= 1
    monkeypatch.setattr(gateway,'_request_one',request)

    async def episode(n):
        task = await AiTask.create(task_type=6, status=2)
        token = current_execution.set(SimpleNamespace(params={'task_id':str(task.id),'remake_context_version':5}))
        paths = [tmp_path/f'{i}.mp4' for i in range(n)]
        try:
            return await analyze_source_shots(paths,[4]*n,{p.name:{'interval':{'start_seconds':i*4,'end_seconds':(i+1)*4}} for i,p in enumerate(paths)},
                                              gateway,'default',{},None,[])
        finally:
            current_execution.reset(token)
    results = await asyncio.gather(*(episode(n) for n in (35,35,33)))
    assert peak == limit and count == 103
    assert all([r['shot_index'] for r in e] == list(range(1,len(e)+1)) for e in results)


@pytest.mark.asyncio
async def test_deadline_cancels_work_and_does_not_report_success():
    import time
    from services.remake.handler import RemakeDecompositionError, RemakeDecompositionTaskHandler
    h=RemakeDecompositionTaskHandler()
    finished=asyncio.Event()
    release_cleanup=asyncio.Event()
    async def work(_):
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
            await release_cleanup.wait()
    h._execute=work
    with pytest.raises(RemakeDecompositionError) as err:
        await asyncio.wait_for(h.execute({'remake_deadline_at':time.time()+.02,'remake_source_id':9999,'novel_id':9999}), .5)
    assert err.value.error_code=='REMAKE_DEADLINE_EXCEEDED' and finished.is_set()
    release_cleanup.set()
    await asyncio.gather(*h._cleanup_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_independent_request_sends_previous_footage_then_current_in_one_call(tmp_path):
    from schemas.agent_workflow import RemakeShot
    from services.creation_agent.skill_execution import current_execution
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from test.test_services.test_remake_gateway import _config, _Client
    from test.remake_fixtures import remake_shot
    from prompts.remake import independent_shot_instruction
    prev,target=(tmp_path/name for name in ['a.mp4','b.mp4'])
    prev.write_bytes(b'PREVIOUS');target.write_bytes(b'CURRENT')
    sample=remake_shot(2)
    answer=RemakeShot.model_validate({k:v for k,v in sample.items() if k in RemakeShot.model_fields})
    generate=AsyncMock(return_value=answer)
    token=current_execution.set(SimpleNamespace(params={'remake_context_version':5},language='zh',generate=generate))
    try:
        gateway=RemakeVideoAnalysisGateway(_config(),client=_Client([]))
        await gateway.analyze_one(index=2,path=target,previous_path=prev,prompt='',context={},
                                  schema_name='professional_video_prompt_material',response_schema={})
    finally:
        current_execution.reset(token)
    call=generate.await_args
    assert generate.await_count==1 and [m.data for m in call.kwargs['media']]==[b'PREVIOUS',b'CURRENT']
    assert call.kwargs['additional_instructions']==independent_shot_instruction('zh')
    assert 'last video' in independent_shot_instruction('en')


@pytest.mark.asyncio
async def test_expired_queued_shot_never_contacts_the_model(tmp_path, monkeypatch):
    from services.creation_agent.skill_execution import current_execution
    from services.remake.gateway import RemakeVideoAnalysisError, RemakeVideoAnalysisGateway
    from test.test_services.test_remake_gateway import _config, _Client
    g=RemakeVideoAnalysisGateway(_config(),client=_Client([]))
    call=AsyncMock()
    monkeypatch.setattr(g,'_request_one',call)
    token=current_execution.set(SimpleNamespace(params={'remake_context_version':5, 'remake_deadline_at':1}))
    try:
        with pytest.raises(RemakeVideoAnalysisError) as err:
            await g.analyze_one(index=1,path=tmp_path/'1.mp4',prompt='',schema_name='global_key_assets',response_schema={})
        assert err.value.error_code=='REMAKE_DEADLINE_EXCEEDED'
        call.assert_not_awaited()
    finally:
        current_execution.reset(token)


def test_same_asset_alias_with_different_case_is_still_unambiguous():
    asset = {'id': 'prop1', 'name': 'Key Card', 'aliases': ['key card']}
    ref = {'asset_type': 'object', 'asset_name': 'KEY CARD', 'asset_id': 'local-1'}
    shot, = bind_shot_references([{'asset_refs': [ref]}], {'objects': [asset]})
    assert [r['asset_id'] for r in shot['asset_refs']] == ['prop1']


@pytest.mark.asyncio
async def test_closed_clip_is_analyzed_before_the_next_clip_is_published(tmp_path):
    from services.remake.single_wave import analyze_ready_shots
    first = asyncio.Event()
    previous = []

    async def ready():
        yield tmp_path/'a.mp4', 4, {'start_seconds':0,'end_seconds':4}, 2
        await asyncio.wait_for(first.wait(), 1)
        yield tmp_path/'b.mp4', 4, {'start_seconds':4,'end_seconds':8}, 2

    async def request(**kwargs):
        previous.append(kwargs['previous_path'])
        first.set()
        return {}

    result = await analyze_ready_shots(ready(), SimpleNamespace(analyze_one=request), 'default', {}, None, [])
    assert [r['file'] for r in result] == ['a.mp4','b.mp4']
    assert previous == [None, tmp_path/'a.mp4']


@pytest.mark.asyncio
async def test_stream_resume_checks_closed_clip_bytes_before_any_model_call(tmp_path):
    from services.remake.pipeline import RemakePipelineError
    from services.remake.single_wave import stream_source_analysis
    path = tmp_path/'scene-001.mp4'
    interval = {'start_seconds': 0, 'end_seconds': 4}

    class Detector:
        async def ready_clips(self, _, directory):
            yield path, interval, 1

    saved = {}
    async def checkpoint(key, snapshot):
        return saved.setdefault(key, await snapshot())
    model = AsyncMock(return_value={})
    args = (Detector(), path, tmp_path, SimpleNamespace(analyze_one=model), 'default', [], saved, checkpoint, None, {})
    path.write_bytes(b'original')
    await stream_source_analysis(*args, cache=True)
    assert model.await_count == 1 and (tmp_path/'manifest.json').exists()
    del saved['remake:timeline']  # Prior attempt ended after the input receipt, before final manifest.
    model.reset_mock()
    path.write_bytes(b'modified')
    with pytest.raises(RemakePipelineError, match='不能复用'):
        await stream_source_analysis(*args, cache=False)
    model.assert_not_awaited()
