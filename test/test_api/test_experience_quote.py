from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from auth.models import Team, TeamMember, User
from config import settings
from models.novel import Novel
from models.video import Video
from schemas.video import VideoReferenceMedia
from schemas.experience import ExperienceQuoteIn
from services.experience_quote import clip_quote
from services.experience import create_clip, start_clip
from test.test_api.test_experience_api import configured, payload
from utils.messages import message_language


async def member_context(balance, *, limit=None, used=0):
    user = await User.create(username='quote-' + uuid4().hex, nickname='报价测试')
    team = await Team.create(name='报价团队',balance=Decimal(str(balance)))
    member = await TeamMember.create(team=team,user=user,role='creator',cost_limit=limit,total_cost=used)
    return AuthContext(user=user,team_id=team.id,membership=member), team


@pytest.mark.parametrize('resolution,expected', [('1K', '0.12'), ('2K', '0.34'), ('4K', '0.56')])
async def test_gpt_image_quote_uses_resolution_tier(resolution, expected):
    from models.config import AiModelConfig

    config = await AiModelConfig.create(task_type=2, task_types=[2], name='GPT Image 2',
        image_model_type='gpt_image_2', model='gpt-image-2', base_url='https://provider.example/v1',
        api_key='test', is_active=True, pricing={'type': 'image', 'prices': {'1K': 0.12, '2K': 0.34, '4K': 0.56}})
    request = ExperienceQuoteIn(task_type='image', mode='direct', model_config_id=config.id,
        resolution=resolution, aspect_ratio='1:1')
    quote = await clip_quote(request, AuthContext())
    assert quote.allowed
    assert quote.estimated_cost == Decimal(expected)


@pytest.mark.asyncio
async def test_quote_matches_settlement_discount_and_duration(configured):
    video, _ = configured
    video.pricing={**video.pricing,'discount':0.5}
    await video.save()
    quote=await clip_quote(payload(video.id,mode='direct'),AuthContext())
    assert quote.estimated_cost == Decimal('0.25')
    assert quote.allowed and quote.available_balance is None
    assert (await clip_quote(payload(video.id,mode='direct').model_copy(update={'duration':10}),AuthContext())).estimated_cost == Decimal('0.5')


@pytest.mark.asyncio
async def test_quote_counts_only_referenced_media_and_includes_reference_image(configured):
    video, _ = configured
    video.pricing={**video.pricing,'video_reference_prices':{'720p':0.2},'input_image':{'first_free':0,'price_per_image':0.05}}
    await video.save()
    refs=[VideoReferenceMedia(type='video',url='/clip.mp4',mention_name='片段',duration=3),VideoReferenceMedia(type='image',url='/pic.png',mention_name='图片')]
    request=payload(video.id,mode='reference').model_copy(update={'reference_binding':'mentions','reference_media':refs,'prompt':'使用 @{片段} 和 @{图片}'})
    quote=await clip_quote(request,AuthContext())
    assert quote.estimated_cost == Decimal('1.40') # output + video input + uploaded/generated image inputs + reference generation
    assert '助手费用' in quote.note
    request.prompt='只使用 @{图片}'
    assert (await clip_quote(request,AuthContext())).estimated_cost == Decimal('0.80')


@pytest.mark.asyncio
async def test_missing_price_or_reference_duration_never_looks_free(configured):
    video, _ = configured
    video.pricing=None
    await video.save()
    quote=await clip_quote(payload(video.id),AuthContext())
    assert quote.estimated_cost is None and not quote.allowed
    video.pricing={'type':'video','currency':'CNY','billing_unit':'second','prices':{'720p':0.1}}
    await video.save()
    request=payload(video.id).model_copy(update={'reference_media':[VideoReferenceMedia(type='video',url='/x.mp4')]})
    quote=await clip_quote(request,AuthContext())
    assert quote.estimated_cost is None and not quote.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize('balance,allowed,shortfall', [('0.49',False,'0.01'),('0.5',True,'0'),('1',True,'0')])
async def test_credit_gate_allows_exact_balance_but_blocks_shortfall(configured,monkeypatch,balance,allowed,shortfall):
    video, _ = configured
    ctx, team=await member_context(balance)
    monkeypatch.setattr(settings,'AUTH_ENABLED',True)
    quote=await clip_quote(payload(video.id,mode='direct'),ctx)
    assert quote.allowed is allowed
    assert quote.shortfall == Decimal(shortfall)
    await team.refresh_from_db()
    assert team.balance == Decimal(balance)


@pytest.mark.asyncio
async def test_member_limit_also_blocks_and_insufficient_request_creates_no_project(configured,monkeypatch):
    video, _ = configured
    ctx, _ = await member_context(10,limit=2,used=Decimal('1.7'))
    monkeypatch.setattr(settings,'AUTH_ENABLED',True)
    quote=await clip_quote(payload(video.id),ctx)
    assert not quote.allowed and quote.available_balance == Decimal('0.3')
    assert '个人' in quote.reason
    before=await Novel.all().count()
    with pytest.raises(HTTPException) as error:
        await create_clip(payload(video.id),ctx)
    assert error.value.status_code == 402
    assert await Novel.all().count() == before


@pytest.mark.asyncio
async def test_start_rechecks_balance_after_creation_and_replay_does_not_charge_twice(configured,monkeypatch):
    video, _ = configured
    ctx, team = await member_context(1)
    monkeypatch.setattr(settings,'AUTH_ENABLED',True)
    session=await create_clip(payload(video.id,mode='direct'),ctx)
    await Team.filter(id=team.id).update(balance=Decimal('0.2'))
    with pytest.raises(HTTPException) as error:
        await start_clip(session['project_id'],ctx)
    assert error.value.status_code == 402
    assert not await Video.filter(scene_id=session['scene_id']).exists()
    await Team.filter(id=team.id).update(balance=1)
    first=await start_clip(session['project_id'],ctx)
    await Team.filter(id=team.id).update(balance=0)
    replay=await start_clip(session['project_id'],ctx)
    assert replay.id == first.id
    assert await Video.filter(scene_id=session['scene_id']).count() == 1


@pytest.mark.asyncio
async def test_read_only_quote_accepts_empty_prompt_and_creates_no_task(client,configured):
    video, _ = configured
    request=ExperienceQuoteIn(model_config_id=video.id,aspect_ratio='16:9',resolution='720p',duration=5)
    before=await Novel.all().count()
    response=await client.post('/api/experience/quote',json=request.model_dump(mode='json'))
    assert response.json()['data']['estimated_cost'] == '0.500000'
    assert await Novel.all().count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('language,expected_reason', [
    ('en', 'Switch to the team you want to create in first'),
    ('zh', '请先切换到要创建作品的团队'),
])
async def test_quote_localizes_team_warning_and_keeps_the_same_estimate(configured, monkeypatch, language, expected_reason):
    video, _ = configured
    monkeypatch.setattr(settings, 'AUTH_ENABLED', True)
    token = message_language.set(language)
    try:
        result = await clip_quote(payload(video.id, mode='direct'), AuthContext())
    finally:
        message_language.reset(token)
    assert result.reason == expected_reason
    assert result.estimated_cost == Decimal('0.5')
    assert not result.allowed
    if language == 'en':
        assert result.note == 'Estimated from the current settings; settled using actual usage.'


@pytest.mark.asyncio
async def test_quote_returns_an_english_pricing_error_without_creating_a_project(configured):
    video, _ = configured
    video.pricing = None
    await video.save()
    before = await Novel.all().count()
    token = message_language.set('en')
    try:
        result = await clip_quote(payload(video.id, mode='direct'), AuthContext())
    finally:
        message_language.reset(token)
    assert result.reason == 'Pricing for this tier is not configured. Contact an administrator.'
    assert result.estimated_cost is None and not result.allowed
    assert await Novel.all().count() == before
