from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.video_enhancement.settlement import settle_enhancement


PRICING={'type':'media_processing','billing_unit':'minute','tiers':[
    {'short_side_max':1080,'fps_max':30,'price':5},
    {'short_side_max':1080,'fps_max':60,'price':10},
    {'short_side_max':1080,'fps_max':120,'price':20}]}


async def completed_export(*,missing=False,novel_id=1,chapter_id=1):
    config=await AiModelConfig.create(task_type=8,name='test-enhancement',model='enhance-video-generative',
        base_url='https://mediakit.example',api_key='secret',api_protocol='volcengine_mediakit',pricing=PRICING,processing_options={})
    snapshot={key:getattr(config,key) for key in ('id','name','model','base_url','api_protocol','scope','team_id','pricing','processing_options')}
    task=await AiTask.create(task_type=8,status=2,request_params={'novel_id':novel_id,'config_snapshot':snapshot})
    export=await ChapterExport.create(novel_id=novel_id,chapter_id=chapter_id,identity_key='1'*64,source_version='2'*64,
        source_probe={'duration':'5','width':864,'height':496,'fps':'24'},
        task=task,provider_task_id='provider-id',provider_result={'status':'completed','result':{} if missing else {
            'duration':5,'fps':24,'resolution':'1080p','video_url':'https://media.example/output.mp4'}})
    return task,export


@pytest.mark.asyncio
async def test_actual_processing_usage_is_billed_once_using_frozen_prices():
    task,export=await completed_export()
    await AiModelConfig.filter(id=task.request_params['config_snapshot']['id']).update(pricing={**PRICING,'discount':10})
    first=await settle_enhancement(task,export)
    second=await settle_enhancement(task,export)
    assert first.id==second.id
    assert first.cost==Decimal('0.416667')
    assert first.usage['seconds']==5 and first.usage['fps']==24
    assert first.pricing_snapshot==PRICING
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count()==1


@pytest.mark.asyncio
async def test_missing_provider_usage_never_becomes_verified_zero_cost():
    task,export=await completed_export(missing=True)
    ledger=await settle_enhancement(task,export)
    assert ledger.cost==0
    assert ledger.usage['missing_usage'] is True
    assert ledger.usage['usage_known'] is False
    assert ledger.usage['seconds'] is None


@pytest.mark.asyncio
async def test_billing_write_failure_rolls_back_receipt_and_can_recover_without_media_submission():
    task,export=await completed_export()
    with patch('services.billing.recorder.billing_recorder._create',AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError):
            await settle_enhancement(task,export)
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count()==0
    assert (await settle_enhancement(task,export)).cost==Decimal('0.416667')


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('duration',50), ('fps',60)])
async def test_reported_usage_conflicting_with_frozen_source_requires_review(field,value):
    task, export = await completed_export()
    export.provider_result['result'][field] = value
    await export.save()
    ledger = await settle_enhancement(task,export)
    assert ledger.cost == 0
    assert ledger.usage['missing_usage'] and ledger.usage['accounting_needs_review']
    assert ledger.usage['submission_outcome_known'] is True
    assert ledger.usage['seconds' if field=='duration' else field] == value
    again = await settle_enhancement(task,export)
    assert again.id == ledger.id and again.cost == 0
