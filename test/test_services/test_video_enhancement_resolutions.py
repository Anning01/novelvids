from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from auth.deps import AuthContext
from controllers.chapter_export import chapter_exports
from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from schemas.video_export import ExportEnhanceIn
from services.creation_agent.waiting import WaitingForMedia
from services.video_enhancement.contract import ENHANCEMENT_PRESET, RESOLUTION_SHORT_SIDE, require_upscale, MediaProbe
from services.video_enhancement.handler import EnhanceExportHandler
from services.video_enhancement.media import export_media, file_digest, inspect_media
from services.video_enhancement.provider import MediaKitClient
from services.video_enhancement.settlement import settle_enhancement
from test.test_services.test_skill_workflow import enabled_project
from test.test_services.test_video_enhancement_billing import completed_export
from test.test_services.test_video_enhancement_media import fixture_video


@pytest.mark.parametrize('resolution,price', [('720p','2.5'),('1080p','5'),('2k','10'),('4k','20')])
@pytest.mark.asyncio
async def test_resolution_is_frozen_in_quote_task_provider_request_and_idempotence(tmp_path, monkeypatch, client, resolution, price):
    novel,chapter,_=await enabled_project()
    path=tmp_path/'source.mp4'; fixture_video(path,size='864x496')
    @asynccontextmanager
    async def materialize(_): yield path
    monkeypatch.setattr(export_media,'materialize',materialize)
    source=await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,identity_key='a'*64,
        source_version='b'*64,source_sha256=file_digest(path),source_media_ref='https://media.example/source.mp4',
        source_probe={**inspect_media(path).model_dump(mode='json'),'duration':'60'})
    config=await AiModelConfig.create(task_type=8,name='MediaKit',api_key='test',is_active=True,**ENHANCEMENT_PRESET)
    response=(await client.get(f'/api/video/exports/{source.id}/quote',params={'model_config_id':config.id,'resolution':resolution})).json()
    assert response['code']==0,response
    quote=response['data']
    assert Decimal(quote['amount'])==Decimal(price)
    request=ExportEnhanceIn(model_config_id=config.id,resolution=resolution,source_sha256=quote['source_sha256'],quote_version=quote['quote_version'])
    first,task=await chapter_exports.enhance(source.id,request,AuthContext())
    again,replay=await chapter_exports.enhance(source.id,request,AuthContext())
    assert first.id==again.id and task.id==replay.id
    assert first.recipe['resolution']==task.request_params['resolution']==resolution
    task.status=2;await task.save()
    with patch('services.video_enhancement.provider.MediaKitClient.submit',AsyncMock(return_value='accepted')) as submit:
        with pytest.raises(WaitingForMedia): await EnhanceExportHandler().execute({**task.request_params,'task_id':str(task.id)})
        assert submit.await_args.kwargs['resolution']==resolution
    assert await AiTask.filter(task_type=8).count()==1
    sent=[]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:(sent.append(req) or httpx.Response(200,json={'success':True,'task_id':'id'})))) as http:
        await MediaKitClient('https://mediakit.example','test',http=http).submit('https://media.example/source.mp4','token',resolution=resolution)
    import json
    assert json.loads(sent[0].content)['resolution']==resolution
    assert 'fps' not in json.loads(sent[0].content)


@pytest.mark.asyncio
async def test_different_target_has_different_quote_and_cannot_reuse_stale_confirmation():
    from fastapi import HTTPException
    novel,chapter,_=await enabled_project()
    config=await AiModelConfig.create(task_type=8,name='MediaKit',api_key='test',is_active=True,**ENHANCEMENT_PRESET)
    source=await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,identity_key='a'*64,source_version='b'*64,
        source_sha256='c'*64,source_media_ref='/media/source.mp4',source_probe={'duration':'5','width':864,'height':496,'fps':24})
    quote=await chapter_exports.quote(source,config.id,AuthContext(),'720p')
    other=await chapter_exports.quote(source,config.id,AuthContext(),'4k')
    assert quote['quote_version']!=other['quote_version']
    with pytest.raises(HTTPException) as caught:
        await chapter_exports.enhance(source.id,ExportEnhanceIn(model_config_id=config.id,resolution='4k',source_sha256=quote['source_sha256'],quote_version=quote['quote_version']),AuthContext())
    assert caught.value.status_code==409
    assert await AiTask.filter(task_type=8).count()==0


@pytest.mark.asyncio
async def test_enhanced_input_uses_its_own_hash_probe_and_bytes(tmp_path,monkeypatch):
    novel,chapter,_=await enabled_project()
    path=tmp_path/'1080p.mp4';fixture_video(path,hd=True)
    @asynccontextmanager
    async def materialize(ref):
        assert ref=='/media/enhanced.mp4'
        yield path
    monkeypatch.setattr(export_media,'materialize',materialize)
    config=await AiModelConfig.create(task_type=8,name='MediaKit',api_key='test',is_active=True,**ENHANCEMENT_PRESET)
    task=await AiTask.create(task_type=8,status=3)
    parent=await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,identity_key='a'*64,source_version='b'*64)
    hd=await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,parent_export_id=parent.id,task=task,
        identity_key='c'*64,source_version='b'*64,source_sha256='d'*64,source_media_ref='/media/original.mp4',
        media_ref='/media/enhanced.mp4',media_sha256=file_digest(path),output_probe=inspect_media(path).model_dump(mode='json'))
    with pytest.raises(ValueError): await chapter_exports.quote(hd,config.id,AuthContext(),'1080p')
    quote=await chapter_exports.quote(hd,config.id,AuthContext(),'2k')
    assert hd.source_sha256=='d'*64  # Read-only quotes cannot rewrite historical evidence.
    request=ExportEnhanceIn(model_config_id=config.id,resolution='2k',source_sha256=quote['source_sha256'],quote_version=quote['quote_version'])
    result,_=await chapter_exports.enhance(hd.id,request,AuthContext())
    assert result.source_sha256==file_digest(path)
    assert result.source_media_ref=='/media/enhanced.mp4'
    assert result.source_probe['height']==1080
    assert result.parent_export_id==hd.id


@pytest.mark.parametrize('resolution,price',[('720p','0.208333'),('2k','0.833333'),('4k','1.666667')])
@pytest.mark.asyncio
async def test_settlement_uses_reported_target_and_never_double_books(resolution,price):
    task,export=await completed_export()
    task.request_params['config_snapshot']['pricing']=ENHANCEMENT_PRESET['pricing'];await task.save()
    export.recipe={'resolution':resolution}
    export.provider_result['result']['resolution']=resolution
    await export.save()
    first=await settle_enhancement(task,export);second=await settle_enhancement(task,export)
    assert first.cost==Decimal(price) and first.id==second.id
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count()==1


@pytest.mark.parametrize('width,height,target',[(1280,720,720),(1920,1080,720),(1080,1920,1080),(2560,1440,1440),(3840,2160,2160)])
def test_equal_or_lower_targets_are_rejected_for_actual_horizontal_and_vertical_pixels(width,height,target):
    with pytest.raises(ValueError): require_upscale(MediaProbe(duration=5,width=width,height=height,fps=24),target)


@pytest.mark.asyncio
async def test_config_rejects_unpriced_enabled_targets_and_keeps_old_1080_only_defaults(client):
    preset={**ENHANCEMENT_PRESET,'name':'targets','task_type':8,'task_types':[8],'api_key':'test'}
    preset['pricing']={**preset['pricing'],'tiers':[tier for tier in preset['pricing']['tiers'] if tier['short_side_max']==1080]}
    response=(await client.post('/api/config',json=preset)).json()
    assert response['code']==400
    old=(await client.post('/api/config',json={**preset,'processing_options':{}})).json()
    assert old['code']==0,old
    assert old['data']['processing_options']['output_resolutions']==['1080p']


@pytest.mark.asyncio
@pytest.mark.parametrize('resolution,size',[('720p','1280x720'),('2k','2560x1440'),('4k','3840x2160')])
async def test_saved_output_is_checked_against_selected_resolution(tmp_path,monkeypatch,resolution,size):
    from types import SimpleNamespace
    from config import settings
    monkeypatch.setattr(settings,'MEDIA_PATH',str(tmp_path))
    monkeypatch.setattr(settings,'CHAPTER_EXPORT_PATH',str(tmp_path.with_name(tmp_path.name+'-exports')))
    source=tmp_path/'source.mp4';fixture_video(source)
    output=tmp_path/'output.mp4';fixture_video(output,size=size)
    export=SimpleNamespace(id=100,team_id=None,recipe={'resolution':resolution},provider_result={'result':{'video_url':'https://download.example/output.mp4'}},
        source_probe=inspect_media(source).model_dump(mode='json'),source_media_ref='/media/source.mp4',source_sha256=file_digest(source))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=output.read_bytes()))) as http:
        saved=await export_media.save_enhanced(export,http)
    assert min(saved['probe']['width'],saved['probe']['height'])==RESOLUTION_SHORT_SIDE[resolution]
    assert resolution in saved['ref']


@pytest.mark.asyncio
async def test_confirmation_label_uses_the_frozen_target_instead_of_1080p():
    from uuid import uuid4
    from services.creation_agent.production import conversation_for_task
    from services.creation_agent.skill_execution import prepare_workflow
    from services.creation_agent.authorization import pending_production
    from models.creation_agent import AgentMessage
    novel,chapter,_=await enabled_project()
    config=await AiModelConfig.create(task_type=8,name='MediaKit',api_key='test',is_active=True,**ENHANCEMENT_PRESET)
    source=await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,identity_key='a'*64,source_version='b'*64,
        source_sha256='c'*64,source_media_ref='/media/source.mp4',source_probe={'duration':'5','width':864,'height':496,'fps':24})
    quote=await chapter_exports.quote(source,config.id,AuthContext(),'2k')
    workflow=await prepare_workflow({'novel_id':novel.id,'prompt_language':'en'})
    task=await AiTask.create(task_type=7,status=2,request_params=workflow)
    await conversation_for_task(task)
    user=await AgentMessage.get(task=task,role='user')
    user.run_input={'request_id':str(uuid4()),'message':'Enhance to 2k','write_scope':'project','production_proposals':[{
        'operation':'enhance_export','target_id':source.id,'request_id':str(uuid4()),'enhancement':{
            'model_config_id':config.id,'resolution':'2k','source_sha256':quote['source_sha256'],'quote_version':quote['quote_version']}}]}
    await user.save()
    pending=await pending_production(task.id)
    assert '2k' in pending['labels'][0]['target_label']
    assert '1080p' not in pending['labels'][0]['target_label']


@pytest.mark.asyncio
async def test_models_show_supported_targets_without_enabling_unpriced_legacy_tiers(client):
    config=await AiModelConfig.create(task_type=8,name='Legacy MediaKit',api_key='secret-must-not-leak',is_active=True,
        **{**ENHANCEMENT_PRESET,'processing_options':{}})
    response=(await client.get('/api/video/exports/models')).json()
    assert response['code']==0,response
    row=next(row for row in response['data'] if row['id']==config.id)
    assert row['resolutions']==[{'value':'1080p','short_side':1080}]
    assert [item['value'] for item in row['supported_resolutions']]==['720p','1080p','2k','4k']
    assert 'api_key' not in row and 'secret-must-not-leak' not in str(response)
    await config.refresh_from_db()
    assert config.processing_options=={}  # Displaying capabilities cannot expand paid configuration.
