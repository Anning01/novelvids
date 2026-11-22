import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.remake.single_wave import analyze_source_shots, bind_shot_references


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
@pytest.mark.parametrize("limit,language", [(None, "zh"), (15, "zh"), (12, "en")])
async def test_independent_request_sends_previous_footage_then_current_in_one_call(tmp_path, limit, language):
    from schemas.agent_workflow import RemakeShot
    from services.creation_agent.skill_execution import current_execution
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from test.test_services.test_remake_gateway import _config, _Client
    from test.remake_fixtures import remake_shot
    from prompts.remake import independent_shot_instruction, source_handoff_instruction
    prev,target=(tmp_path/name for name in ['a.mp4','b.mp4'])
    prev.write_bytes(b'PREVIOUS');target.write_bytes(b'CURRENT')
    sample=remake_shot(2)
    answer=RemakeShot.model_validate({k:v for k,v in sample.items() if k in RemakeShot.model_fields})
    generate=AsyncMock(return_value=answer)
    params = {'remake_context_version': 5}
    if limit is not None:
        params['remake_shot_limit'] = limit
    token=current_execution.set(SimpleNamespace(params=params,language=language,generate=generate))
    try:
        gateway=RemakeVideoAnalysisGateway(_config(),client=_Client([]))
        await gateway.analyze_one(index=2,path=target,previous_path=prev,prompt='',context={},
                                  schema_name='professional_video_prompt_material',response_schema={})
    finally:
        current_execution.reset(token)
    call=generate.await_args
    assert generate.await_count==1 and [m.data for m in call.kwargs['media']]==[b'PREVIOUS',b'CURRENT']
    instructions = independent_shot_instruction(language)
    if limit is not None:
        handoff = source_handoff_instruction(language)
        assert 'output_seconds' in handoff and 'confirmed_handoff' in handoff
        assert ('已完成' if language == 'zh' else 'completed') in handoff
        instructions += '\n' + handoff
    assert call.kwargs['additional_instructions'] == instructions
    assert 'last video' in independent_shot_instruction('en')


@pytest.mark.asyncio
async def test_queued_shot_is_admitted_even_with_an_expired_legacy_deadline(tmp_path, monkeypatch):
    from services.creation_agent.skill_execution import current_execution
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from test.test_services.test_remake_gateway import _config, _Client
    g=RemakeVideoAnalysisGateway(_config(),client=_Client([]))
    call=AsyncMock()
    monkeypatch.setattr(g,'_request_one',call)
    token=current_execution.set(SimpleNamespace(params={'remake_context_version':5, 'remake_deadline_at':1}))
    try:
        await g.analyze_one(index=1,path=tmp_path/'1.mp4',prompt='',schema_name='global_key_assets',response_schema={})
        call.assert_awaited_once()
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


def test_cast_is_bound_by_observed_source_intervals_even_if_model_uses_generic_names():
    def person(i, name, spans):
        return {'id': f'character-{i}', 'name': name, 'appearances': [
            {'start_seconds': a, 'end_seconds': b} for a, b in spans]}
    assets = {'characters': [person(1, '被束缚男子', [(0, 1), (2, 3)]),
                             person(2, '海滩女子', [(2, 3)])]}
    shots = [{'description':'男子', 'source_interval':{'start_seconds':i,'end_seconds':i+1},
              'visible_asset_names':[], 'asset_refs':[]} for i in range(3)]
    rows = bind_shot_references(shots, assets)
    names = [[r['asset_name'] for r in row['asset_refs']] for row in rows]
    assert names == [['被束缚男子'], [], ['被束缚男子', '海滩女子']]
    assert [r['visible_asset_names'] for r in rows] == names
    shots[0]['asset_refs'] = [{'asset_type':'character','asset_name':'被束缚男子','asset_id':'local'}]
    assert len(bind_shot_references(shots[:1],assets)[0]['asset_refs']) == 1


def test_cast_inventory_preserves_verified_ranges_through_asset_rendering():
    from pydantic import ValidationError
    from schemas.agent_workflow import CastAppearance, RemakeCastAssets
    from services.remake.asset_validation import render_remake_assets
    from prompts.remake import cast_appearance_instruction, cast_reference_instruction
    from test.remake_fixtures import design_fields, synthetic_snapshot
    raw = {'characters':[{'name':'男孩','description':'男孩站在岸边','visual_fields':design_fields(),
                          'appearances':[{'start_seconds':1,'end_seconds':2}]}], 'scenes':[], 'objects':[]}
    output = RemakeCastAssets.model_validate(raw)
    rendered = render_remake_assets(output.model_dump(), synthetic_snapshot(), 'zh', '9:16')
    assert RemakeCastAssets.model_validate(rendered).characters[0].appearances == output.characters[0].appearances
    assert all('appearances' in cast_appearance_instruction(lang) and 'asset_refs' in cast_reference_instruction(lang) for lang in ('zh','en'))
    with pytest.raises(ValidationError):
        CastAppearance(start_seconds=2, end_seconds=2)


@pytest.mark.asyncio
async def test_new_asset_request_collects_cast_appearances_in_its_existing_model_call(tmp_path):
    from schemas.agent_workflow import RemakeCastAssets
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from services.creation_agent.skill_execution import current_execution
    from test.test_services.test_remake_gateway import _config, _Client
    from prompts.remake import cast_appearance_instruction
    src = tmp_path/'film.mp4'
    src.write_bytes(b'film')
    response = RemakeCastAssets(characters=[],scenes=[],objects=[])
    generate = AsyncMock(return_value=response)
    gateway = RemakeVideoAnalysisGateway(_config(),client=_Client([]))
    token = current_execution.set(SimpleNamespace(params={'remake_context_version':5,'remake_cast_appearances':True},
                                                 language='zh',generate=generate))
    try:
        await gateway.analyze_one(index=1,path=src,prompt='',context={},schema_name='global_key_assets',response_schema={})
    finally:
        current_execution.reset(token)
    assert generate.await_count == 1 and generate.await_args.args[2] is RemakeCastAssets
    assert cast_appearance_instruction('zh') in generate.await_args.kwargs['additional_instructions']


def test_settings_and_props_follow_visible_intervals_across_cuts_and_do_not_duplicate_named_refs():
    def item(key, name, spans):
        return {'id': key, 'name': name, 'appearances': [
            {'start_seconds': a, 'end_seconds': b} for a, b in spans]}
    assets = {'scenes': [item('s1','实验舱',[(0,4)]), item('s2','海滩',[(4,7)]),
                         item('s3','片尾白底',[(7,8)])],
              'objects': [item('o1','红椅子',[(0,1),(6,7)]), item('o2','甜筒',[(1,8)])]}
    shots = [{'source_interval': {'start_seconds': i, 'end_seconds': i+2}, 'visible_asset_names': [],
              'asset_refs': []} for i in range(0,8,2)]
    shots[0]['asset_refs'] = [{'asset_type':'object','asset_name':'甜筒','asset_id':'temporary'}]
    result = bind_shot_references(shots, assets)
    assert [[r['asset_id'] for r in s['asset_refs']] for s in result] == [
        ['o2','s1','o1'], ['s1','o2'], ['s2','o2'], ['s2','s3','o1','o2']]
    assert result[-1]['visible_asset_names'] == ['海滩','片尾白底','红椅子','甜筒']


@pytest.mark.asyncio
async def test_new_visual_inventory_preserves_scene_and_prop_appearances_in_one_request(tmp_path):
    from schemas.agent_workflow import RemakeTimedAssets, RemakeCastAssets, remake_asset_schema
    from services.remake.asset_validation import render_remake_assets
    from prompts.remake import visual_asset_instruction
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from services.creation_agent.skill_execution import current_execution
    from test.test_services.test_remake_gateway import _config, _Client
    from test.remake_fixtures import design_fields, synthetic_snapshot
    span = [{'start_seconds':1, 'end_seconds':2}]
    raw = RemakeTimedAssets.model_validate({'characters':[], 'scenes':[{'name':'海滩','description':'海边',
        'visual_fields':design_fields(kind='scene'),'appearances':span}], 'objects':[{'name':'甜筒',
        'description':'冰淇淋','visual_fields':design_fields(kind='item'),'appearances':span}]})
    rendered = render_remake_assets(raw.model_dump(),synthetic_snapshot(),'zh','9:16')
    assert RemakeTimedAssets.model_validate(rendered).objects[0].appearances == raw.scenes[0].appearances
    src = tmp_path/'clip.mp4'; src.write_bytes(b'clip')
    generate = AsyncMock(return_value=raw)
    token = current_execution.set(SimpleNamespace(params={'remake_context_version':5,'remake_asset_appearances':True,
        'remake_cast_appearances':True}, language='zh',generate=generate))
    try:
        await RemakeVideoAnalysisGateway(_config(), client=_Client([])).analyze_one(index=1,path=src,prompt='',
            context={},schema_name='global_key_assets',response_schema={})
    finally:
        current_execution.reset(token)
    assert generate.await_count == 1 and generate.await_args.args[2] is RemakeTimedAssets
    assert visual_asset_instruction('zh', inventory=True) in generate.await_args.kwargs['additional_instructions']
    assert 'appearances' in visual_asset_instruction('en', inventory=True)
    assert remake_asset_schema({'remake_cast_appearances':True}) is RemakeCastAssets


def test_repeated_prop_inventory_entries_keep_their_separate_sightings():
    from prompts.remake_render import normalize_global_assets
    asset = {'name':'同款甜筒','description':'水果双球'}
    spans = [{'start_seconds':1,'end_seconds':2}, {'start_seconds':6,'end_seconds':8}]
    rows = [{**asset, 'appearances':[span]} for span in spans]
    normalized = normalize_global_assets({'objects':rows + rows}, separate_conflicts=True)
    prop, = normalized['objects']
    assert prop['appearances'] == spans
    assert rows[0]['appearances'] == spans[:1]


def test_missing_visual_groups_are_rebuilt_from_shot_local_names_and_bound_per_shot():
    from services.remake.single_wave import missing_visual_groups
    from services.remake.prompt_render import normalize_global_assets

    def shot(index, *refs):
        return {'shot_index': index, 'asset_refs': [
            {'asset_id': str(i), 'asset_type': kind, 'asset_name': name} for i,(kind,name) in enumerate(refs)]}
    shots = [shot(1, ('character','旅客'),('scene','工作间'),('object','蓝杯')),
             shot(2, ('character','旅客'),('character','店员'),('scene','阳台'),('object','蓝杯'),('object','桌子'))]
    assets = {'characters': [], 'scenes': [], 'objects': []}
    extra = missing_visual_groups(shots, assets)
    registered = normalize_global_assets(extra)
    assert [item['name'] for item in registered['objects']] == ['蓝杯','桌子']
    rows = bind_shot_references(shots, registered)
    assert [[r['asset_name'] for r in row['asset_refs']] for row in rows] == [['旅客','工作间','蓝杯'],['旅客','店员','阳台','蓝杯','桌子']]
    assert not missing_visual_groups(shots, registered)
