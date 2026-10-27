"""Validated media processing configuration and output-duration pricing."""

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field

from utils.messages import localized_message


class EnhancementOptions(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    input_short_side_min: int = Field(360, ge=1)
    input_short_side_max: int = Field(1080, ge=1)
    input_long_side_max: int = Field(1920, ge=1)
    input_fps_min: Decimal = Field(Decimal('15'), gt=0)
    input_fps_max: Decimal = Field(Decimal('120'), gt=0)
    max_duration_seconds: Decimal | None = Field(None, gt=0)
    max_file_bytes: int | None = Field(None, gt=0)
    poll_seconds: int = Field(15, ge=5, le=300)
    account_concurrency: int = Field(20, ge=1, le=1000)
    queue_id: str | None = Field(None, max_length=100)
    media_base_url: str | None = Field(None, max_length=500)
    local_upload_max_bytes: int = Field(5 * 1024 ** 3, gt=0)


class MediaProbe(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    duration: Decimal = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: Decimal = Field(gt=0)
    color_transfer: str | None = None
    audio_streams: list[dict] = Field(default_factory=list)
    size: int = Field(0, ge=0)


def validate_source(probe: MediaProbe, options: EnhancementOptions) -> None:
    short, long = sorted((probe.width, probe.height))
    if not options.input_short_side_min <= short <= options.input_short_side_max or long > options.input_long_side_max:
        raise ValueError(localized_message('原片尺寸超出画质增强配置的范围'))
    if not options.input_fps_min <= probe.fps <= options.input_fps_max:
        raise ValueError(localized_message('原片帧率超出画质增强配置的范围'))
    if probe.color_transfer in {'smpte2084', 'arib-std-b67'}:
        raise ValueError(localized_message('画质增强仅支持 SDR 原片'))
    if options.max_duration_seconds is not None and probe.duration > options.max_duration_seconds:
        raise ValueError(localized_message('原片时长超出管理员配置的范围'))
    if options.max_file_bytes is not None and probe.size > options.max_file_bytes:
        raise ValueError(localized_message('原片大小超出管理员配置的范围'))


class PriceTier(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    short_side_max: int = Field(gt=0)
    fps_max: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)


class EnhancementPricing(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    type: str = 'media_processing'
    billing_unit: str = 'minute'
    currency: str = 'CNY'
    discount: Decimal = Field(Decimal('1'), gt=0)
    discount_description: str | None = None
    tiers: list[PriceTier] = Field(min_length=1)


ENHANCEMENT_PRESET = {
    'base_url': 'https://mediakit.cn-beijing.volces.com',
    'model': 'enhance-video-generative',
    'api_protocol': 'volcengine_mediakit',
    'processing_options': EnhancementOptions().model_dump(mode='json'),
    'pricing': {'type': 'media_processing', 'currency':'CNY', 'billing_unit':'minute', 'tiers': [
        {'short_side_max':1080, 'fps_max':30, 'price':5},
        {'short_side_max':1080, 'fps_max':60, 'price':10},
        {'short_side_max':1080, 'fps_max':120, 'price':20},
    ]},
}


def enhancement_cost(seconds, short_side: int, fps, pricing: dict) -> Decimal:
    price = EnhancementPricing.model_validate(pricing)
    if price.type != 'media_processing' or price.billing_unit != 'minute' or price.currency != 'CNY':
        raise ValueError(localized_message('画质增强需要按分钟配置媒体处理价格'))
    try:
        duration, rate = Decimal(str(seconds)), Decimal(str(fps))
    except Exception:
        raise ValueError(localized_message('画质增强缺少实际时长或帧率')) from None
    if not duration.is_finite() or not rate.is_finite() or duration <= 0 or rate <= 0 or short_side <= 0:
        raise ValueError(localized_message('画质增强缺少实际时长或帧率'))
    tiers = sorted(price.tiers, key=lambda tier: (tier.short_side_max, tier.fps_max))
    tier = next((tier for tier in tiers if short_side <= tier.short_side_max and rate <= tier.fps_max), None)
    if tier is None:
        raise ValueError(localized_message('画质增强未配置当前规格的价格'))
    return (duration / 60 * tier.price * price.discount).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
