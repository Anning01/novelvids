import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from prompts.remake import short_storyboard_instruction
from prompts.skill_pack import instructions
from schemas.remake_short import RemakeShortStoryboard, ShortShot, ShotLook
from services.remake.gateway import RemakeVideoAnalysisError
from services.remake.output_recovery import recover_short_rows, recover_shot_text
from services.remake.short_admission import run_admitted
from services.remake.single_wave import analyze_short_storyboard
from test.remake_fixtures import remake_shot, synthetic_snapshot


def sample(count=5):
    whole = remake_shot(1)
    look = {k: whole[k] for k in ShotLook.model_fields}
    shots = []
    for i in range(1, count+1):
        v = remake_shot(i)
        shots.append({k: v[k] for k in ShortShot.model_fields if k != 'look'} | {'look': 1})
    return {'looks': [look], 'shots': shots}


def test_wire_contract_uses_existing_rules_and_validates_exact_indices_and_look():
    data = sample(); spans = [{'sequence':i,'start_seconds':i*3,'end_seconds':i*3+3.1} for i in range(1,6)]
    rows = RemakeShortStoryboard.model_validate(data).materialize(spans)
    assert len(rows)==5 and all(r['duration']=='3.1s' for r in rows.values())
    for language in ('zh','en'):
        assert instructions(synthetic_snapshot(),language,'remake',output_kind='short_video_storyboard') == instructions(
            synthetic_snapshot(),language,'remake',output_kind='professional_video_prompt_material')
        assert 'looks' in short_storyboard_instruction(language)
    data['shots'][1]['sequence']=1
    with pytest.raises(ValueError,match='Shot numbers'):
        RemakeShortStoryboard.model_validate(data).materialize(spans)
    data['shots'][1].update(sequence=2,look=9)
    with pytest.raises(ValueError,match='Unknown shot look'):
        RemakeShortStoryboard.model_validate(data).materialize(spans)


@pytest.mark.asyncio
async def test_five_source_intervals_use_one_request_and_restore_without_another(tmp_path):
    paths=[tmp_path/f'{i}.mp4' for i in range(5)]
    evidence={p.name:{'interval':{'start_seconds':i*4,'end_seconds':i*4+4}} for i,p in enumerate(paths)}
    data=sample(); saved={}
    gateway=SimpleNamespace(analyze_one=AsyncMock(return_value=data),config=SimpleNamespace())
    async def checkpoint(key, fn):
        saved[key]=await fn()
        return saved[key]
    args=(tmp_path/'entire.mp4',paths,evidence,gateway,'default',saved,checkpoint,AsyncMock(),[],{'task_id':'test'})
    first=await analyze_short_storyboard(*args)
    assert [x['shot_index'] for x in first]==[1,2,3,4,5]
    assert gateway.analyze_one.await_count==1 and gateway.analyze_one.await_args.kwargs['path']==args[0]
    assert len(gateway.analyze_one.await_args.kwargs['context']['intervals'])==5
    del saved['model:remake:RemakeShot:3']
    saved['model:remake:RemakeShortStoryboard:1']=data
    assert await analyze_short_storyboard(*args)==first
    assert gateway.analyze_one.await_count==1


@pytest.mark.asyncio
@pytest.mark.parametrize('confirmed,expected', [(True,2),(False,1)])
async def test_429_is_retried_only_on_verified_uncharged_rejection(monkeypatch,confirmed,expected):
    probe=AsyncMock(return_value=confirmed);monkeypatch.setattr('services.remake.short_admission.confirmed_rejection',probe)
    error=RemakeVideoAnalysisError('429',error_code='REMAKE_ANALYSIS_RATE_LIMITED')
    invoke=AsyncMock(side_effect=[error,'returned'])
    params={'task_id':'test','remake_deadline_at':time.time()+5}
    if confirmed:
        assert await run_admitted(invoke,object(),params,'RemakeShortStoryboard')=='returned'
        assert invoke.await_args.args==('1-readmit',)
    else:
        with pytest.raises(RemakeVideoAnalysisError):
            await run_admitted(invoke,object(),params,'RemakeShortStoryboard')
    assert invoke.await_count==expected
    probe.assert_awaited_once()


def test_truncated_stream_retains_only_fully_returned_shots_and_closed_creative_fields():
    data=sample(); intervals=[{'sequence':i,'start_seconds':i*4,'end_seconds':i*4+4} for i in range(1,6)]
    text=json.dumps(data,ensure_ascii=False)
    partial=text[:text.index('"description":',text.index('"sequence": 5'))]+'"description":"cut'
    assert list(recover_short_rows(partial,intervals))==[1,2,3,4]
    assert len(recover_short_rows(text[:-2],intervals))==5
    raw=remake_shot()
    from schemas.agent_workflow import RemakeShot
    raw=RemakeShot.model_validate({k:v for k,v in raw.items() if k in RemakeShot.model_fields}).model_dump()
    raw.pop('segments')
    tail=',"segments":[{"visual_prose":"cut'
    fixed=recover_shot_text(json.dumps(raw)[:-1]+tail)
    assert fixed and fixed.actions==raw['actions'] and not fixed.segments
    for critical in ['actions','asset_refs','dialogue','narration']:
        incomplete={k:v for k,v in raw.items() if k!=critical}
        assert recover_shot_text(json.dumps(incomplete)[:-1]+tail) is None
    assert recover_shot_text(json.dumps(raw)[:-1]+',"segments":[bad-json') is None


@pytest.mark.asyncio
async def test_receipt_verification_rejects_wrong_identity_pending_and_charge(monkeypatch):
    from uuid import uuid4
    import httpx
    from services.remake.short_admission import confirmed_rejection
    from models.studio_call import StudioCall
    from models.usage_record import ModelUsageRecord
    parent, receipt_id=uuid4(),uuid4()
    cfg=SimpleNamespace(api_protocol='novelvids',base_url='https://studio.test/v1',api_key='test',id=3,model='nv-3')
    monkeypatch.setattr(ModelUsageRecord,'filter',lambda **_:SimpleNamespace(values_list=AsyncMock(return_value=[4])))
    monkeypatch.setattr(StudioCall,'filter',lambda **_:SimpleNamespace(limit=AsyncMock(return_value=[
        SimpleNamespace(platform_request_id=receipt_id,base_url=cfg.base_url)])))
    data={'id':str(receipt_id),'model':cfg.model,'status':'rejected','usage':{},'settlement':{'status':'not_charged'},'pricing':{}}
    real=httpx.AsyncClient
    def http_reply(req):
        assert req.method=='GET' and str(req.url).endswith('/requests/'+str(receipt_id))
        return httpx.Response(200,json=data)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(http_reply)))
    async def verified():
        return await confirmed_rejection(cfg,parent,'model:remake:RemakeShortStoryboard:1',time.time()+10)
    assert await verified()
    for field, val in [('model','nv-other'),('id',str(uuid4())),('status','review'),('settlement',{'status':'pending'})]:
        old=data[field];data[field]=val
        assert not await verified()
        data[field]=old


@pytest.mark.asyncio
async def test_batch_stream_break_keeps_closed_rows_without_replaying(monkeypatch,tmp_path):
    data=sample(5)
    text=json.dumps(data)
    end=text.index('"description":',text.index('"sequence": 5'))
    monkeypatch.setattr('services.remake.output_recovery.latest_response_text',AsyncMock(return_value=text[:end]))
    paths=[tmp_path/f'{i}.mp4' for i in range(5)]
    evidence={p.name:{'interval':{'start_seconds':i,'end_seconds':i+1}} for i,p in enumerate(paths)}
    saved={}
    async def checkpoint(key, fn):
        saved[key]=await fn()
        return saved[key]
    gateway=SimpleNamespace(config=SimpleNamespace(),analyze_one=AsyncMock(side_effect=RuntimeError("disconnected")))
    with pytest.raises(RuntimeError, match='disconnected'):
        await analyze_short_storyboard(tmp_path/'src.mp4',paths,evidence,gateway,'default',saved,checkpoint,AsyncMock(),[],{'task_id':'test'})
    assert {k for k in saved if k.startswith('model:')}=={f'model:remake:RemakeShot:{i}' for i in (1,2,3,4)}
    gateway.analyze_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_gateway_sends_original_video_once_and_checks_output_before_accepting(tmp_path):
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from services.creation_agent.skill_execution import current_execution
    from test.test_services.test_remake_gateway import _config, _Client
    src = tmp_path/'full.mp4'
    src.write_bytes(b'ORIGINAL VIDEO')
    response = RemakeShortStoryboard.model_validate(sample())
    generate = AsyncMock(return_value=response)
    gateway = RemakeVideoAnalysisGateway(_config(),client=_Client([]))
    token = current_execution.set(SimpleNamespace(params={'remake_context_version':5},language='zh',generate=generate))
    cuts = [{'sequence':i, 'start_seconds':i*4, 'end_seconds':(i+1)*4} for i in range(1,6)]
    try:
        raw = await gateway.analyze_one(index=1, path=src, schema_name='short_video_storyboard',
            prompt='', response_schema={}, context={'intervals':cuts}, include_segment_metadata=False)
    finally:
        current_execution.reset(token)
    call=generate.await_args
    assert generate.await_count==1 and len(raw['shots'])==5
    assert [m.data for m in call.kwargs['media']]==[b'ORIGINAL VIDEO']
    assert call.args[:3]==('remake',{'segment':1,'assets':{'intervals':cuts},'output_kind':'short_video_storyboard'},RemakeShortStoryboard)
    await call.kwargs['output_validator'](response)
    with pytest.raises(ValueError):
        await call.kwargs['output_validator'](response.model_copy(update={'shots':response.shots[:-1]}))


@pytest.mark.asyncio
async def test_retry_is_bounded_and_never_replays_an_unknown_stream(monkeypatch):
    denied=RemakeVideoAnalysisError('429',error_code='REMAKE_ANALYSIS_RATE_LIMITED')
    probe=AsyncMock(return_value=True)
    monkeypatch.setattr('services.remake.short_admission.confirmed_rejection',probe)
    params={'task_id':'test','remake_deadline_at':time.time()+10}
    call=AsyncMock(side_effect=denied)
    with pytest.raises(RemakeVideoAnalysisError):
        await run_admitted(call,object(),params,'RemakeAssets')
    assert call.await_count==2
    call=AsyncMock(side_effect=TimeoutError('unknown outcome'))
    with pytest.raises(TimeoutError):
        await run_admitted(call,object(),params,'RemakeAssets')
    call.assert_awaited_once_with(None)
    probe.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_resume_reads_existing_batch_stream_before_deciding_whether_it_is_safe_to_continue(complete):
    from uuid import uuid4, uuid5
    from models.ai_task import AiTask
    from models.agent_operation import AgentOperation
    from models.creation_agent import AgentConversation, AgentMessage
    from models.novel import Novel
    from exceptions.remake import RemakeError
    from services.remake.checkpoints import reconcile_retry
    novel=await Novel.create(name='短片衔接',workflow_kind='remake')
    task=await AiTask.create(task_type=6,status=4,request_params={'remake_context_version':5,'remake_short_storyboard':True})
    key='model:remake:RemakeShortStoryboard:1'
    child=await AiTask.create(id=uuid5(task.id,key),task_type=8,status=4)
    await AgentMessage.create(task=child,conversation=await AgentConversation.create(novel=novel),role='assistant',
                              request_id=uuid4(),request_hash='',usage={'calls':[{'status':'failed'}]})
    text=json.dumps(sample())
    cut=text[:-2] if complete else text[:text.index('"description":',text.index('"sequence": 5'))]
    await AgentOperation.create(task=child,key='model-response:1:0',state='completed',result={
        'messages':[{'parts':[{'part_kind':'text','content':cut}]}]})
    await AgentOperation.create(task=task,key=key,external=True,state='uncertain')
    await AgentOperation.create(task=task,key='remake:short-input',state='completed',result={
        'intervals':[{'sequence':i,'start_seconds':i*2,'end_seconds':i*2+2} for i in range(1,6)]})
    if complete:
        await reconcile_retry(task)
    else:
        with pytest.raises(RemakeError) as err:
            await reconcile_retry(task)
        assert err.value.error_code=='REMAKE_AWAITING_RECEIPT'
    assert await AgentOperation.filter(task=task,key__startswith='model:remake:RemakeShot:',state='completed').count()==(5 if complete else 4)
    assert await AgentOperation.filter(task=task,key=key,state='uncertain').exists()
