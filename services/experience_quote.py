"""Read-only clip estimates, using the same pricing math as settlement."""
from decimal import Decimal, InvalidOperation
import math

from fastapi import HTTPException
from pydantic import BaseModel

from auth.deps import AuthContext
from config import settings
from controllers.config import ai_model_config_controller
from prompts.experience import render_named_references, with_references
from schemas.experience import ExperienceQuoteIn, ExperienceGenerateIn
from services.billing.pricing import compute_image_cost, compute_input_image_cost, compute_video_cost, TOKENS_PER_SECOND
from services.image_generation.capabilities import validate_selection as image_selection
from services.video.capabilities import validate_selection as video_selection
from services.video.reference_media import reference_mention_syntax, select_referenced_media


class ClipQuote(BaseModel):
    estimated_cost: Decimal | None = None
    original_cost: Decimal | None = None
    discount: Decimal | None = None
    discount_description: str | None = None
    available_balance: Decimal | None = None
    shortfall: Decimal | None = None
    currency: str = 'CNY'
    allowed: bool = False
    reason: str = ''
    note: str = ''


def _price(pricing, kind, tier):
    if not isinstance(pricing, dict) or pricing.get('type') != kind or tier not in (pricing.get('prices') or {}):
        raise ValueError('当前模型尚未配置该档位价格，请联系管理员')
    if pricing.get('currency', 'CNY') != 'CNY':
        raise ValueError('当前价格币种无法与人民币余额核对，请联系管理员')
    try:
        value = Decimal(str(pricing['prices'][tier]))
        discount = Decimal(str(pricing['discount'] if pricing.get('discount') is not None else 1))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('模型价格配置无效，请联系管理员') from None
    if not value.is_finite() or value < 0 or not discount.is_finite() or discount <= 0:
        raise ValueError('模型价格配置无效，请联系管理员')
    fee = pricing.get('input_image')
    if fee is not None:
        try:
            unit = Decimal(str(fee['price_per_image']))
            free = Decimal(str(fee.get('first_free', 0)))
        except (InvalidOperation, TypeError, ValueError, KeyError):
            raise ValueError('参考图片价格配置无效，请联系管理员') from None
        if not unit.is_finite() or unit < 0 or not free.is_finite() or free < 0 or free != free.to_integral_value():
            raise ValueError('参考图片价格配置无效，请联系管理员')
    return pricing


def _references(payload):
    if payload.reference_binding == 'mentions':
        prompt = render_named_references(payload.prompt, {
            item.mention_name: reference_mention_syntax(item.type, item.mention_url or item.url)
            for item in payload.reference_media
        })
    else:
        prompt = with_references(payload.prompt, [reference_mention_syntax(item.type, item.mention_url or item.url) for item in payload.reference_media])
    return select_referenced_media(prompt, payload.reference_media)


async def clip_quote(payload: ExperienceQuoteIn | ExperienceGenerateIn, ctx: AuthContext, *, reference_image_config_id: int | None = None) -> ClipQuote:
    note = '按当前参数估算，最终按实际用量结算。'
    if payload.mode != 'direct':
        note = '图片/视频按当前参数估算，助手费用按实际用量另计。'
    quote = ClipQuote(note=note)
    config = await ai_model_config_controller.get_active(4 if payload.task_type == 'video' else 2,
        payload.model_config_id, team_id=ctx.team_id)
    try:
        if payload.task_type == 'video':
            selected = video_selection(config.video_model_type, api_protocol=config.api_protocol, generation_mode='reference', resolution=payload.resolution,
                aspect_ratio=payload.aspect_ratio, duration=payload.duration, output_format=None, generate_audio=None)
            pricing = _price(config.pricing, 'video', selected.resolution)
            if pricing.get('billing_unit') != 'second' and selected.resolution not in TOKENS_PER_SECOND:
                raise ValueError('当前档位无法计算预计价格，请联系管理员')
            references = _references(payload)
            videos = [item for item in references if item.type == 'video']
            if any(item.duration is None or not math.isfinite(item.duration) or item.duration <= 0 for item in videos):
                raise ValueError('参考视频时长尚未确认，暂时无法报价')
            reference_prices = pricing.get('video_reference_prices')
            if videos and reference_prices:
                _price({**pricing, 'prices': reference_prices}, 'video', selected.resolution)
            total = compute_video_cost(payload.duration, selected.resolution, pricing,
                input_video_seconds=sum(item.duration for item in videos), has_video_reference=bool(videos),
                input_image_count=sum(item.type == 'image' for item in references) + int(payload.mode == 'reference'))
            pricing_undiscounted = {**pricing, 'discount': 1}
            original_total = compute_video_cost(payload.duration, selected.resolution, pricing_undiscounted,
                input_video_seconds=sum(item.duration for item in videos), has_video_reference=bool(videos),
                input_image_count=sum(item.type == 'image' for item in references) + int(payload.mode == 'reference'))
        else:
            selected = image_selection(config.image_model_type, clarity=payload.resolution, aspect_ratio=payload.aspect_ratio,
                output_format='png', generation_count=1)
            image_pricing = _price(config.pricing, 'image', selected.clarity)
            references = _references(payload)
            input_image_count = sum(item.type == 'image' for item in references)
            total = compute_image_cost(1, selected.clarity, image_pricing) + compute_input_image_cost(input_image_count, image_pricing)
            pricing_undiscounted = {**image_pricing, 'discount': 1}
            original_total = compute_image_cost(1, selected.clarity, pricing_undiscounted) + compute_input_image_cost(input_image_count, pricing_undiscounted)
        if payload.mode == 'reference':
            reference_config = await ai_model_config_controller.get_active(2, reference_image_config_id, team_id=ctx.team_id)
            reference_selection = image_selection(reference_config.image_model_type, clarity=None, aspect_ratio=payload.aspect_ratio,
                output_format='png', generation_count=1)
            ref_pricing = _price(reference_config.pricing, 'image', reference_selection.clarity)
            total += compute_image_cost(1, reference_selection.clarity, ref_pricing)
            ref_undiscounted = {**ref_pricing, 'discount': 1}
            original_total += compute_image_cost(1, reference_selection.clarity, ref_undiscounted)
        if not total.is_finite() or total < 0:
            raise ValueError('无法确认预计价格，请联系管理员')
        target_pricing = pricing if payload.task_type == 'video' else image_pricing
        model_discount = Decimal(str(target_pricing.get('discount') or 1)) if isinstance(target_pricing, dict) else Decimal('1')
        quote.discount = model_discount
        quote.discount_description = target_pricing.get('discount_description') if isinstance(target_pricing, dict) else None
        quote.original_cost = original_total if model_discount < Decimal('1') else total
    except ValueError as error:
        quote.reason = str(error)
        return quote
    except InvalidOperation:
        quote.reason = '无法确认预计价格，请联系管理员'
        return quote
    quote.estimated_cost = total
    if not settings.AUTH_ENABLED:
        quote.allowed = True
        return quote
    if ctx.team_id is None:
        quote.reason = '请先切换到要创建作品的团队'
        return quote
    from auth.models import Team, TeamMember
    team = await Team.get_or_none(id=ctx.team_id)
    if team is None:
        raise HTTPException(404, '团队不存在')
    balance = Decimal(str(team.balance))
    member = await TeamMember.get_or_none(team_id=ctx.team_id, user_id=ctx.user.id) if ctx.user else None
    remaining = None
    if member and member.cost_limit is not None:
        remaining = max(Decimal('0'), Decimal(str(member.cost_limit)) - Decimal(str(member.total_cost)))
    quote.available_balance = min(balance, remaining) if remaining is not None else balance
    quote.shortfall = max(Decimal('0'), total - quote.available_balance)
    if not ctx.is_super_admin and (member is None or member.role not in ('admin', 'creator')):
        quote.reason = '当前账号没有创作权限'
    elif balance < total or balance <= 0:
        quote.reason = '团队余额不足，请先充值'
    elif remaining is not None and (remaining < total or remaining <= 0):
        quote.reason = '个人消费限额不足，请联系管理员调整'
    else:
        quote.allowed = True
    return quote


async def require_clip_funds(payload: ExperienceGenerateIn, ctx: AuthContext, *, reference_image_config_id: int | None = None) -> None:
    quote = await clip_quote(payload, ctx, reference_image_config_id=reference_image_config_id)
    if not quote.allowed:
        raise HTTPException(402 if quote.estimated_cost is not None and quote.available_balance is not None else 409, quote.reason)
