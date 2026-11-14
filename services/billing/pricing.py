"""计费规则：token 归一化与三种维度的成本计算。"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY_QUANT = Decimal("0.000001")
_TOKEN_DIVISOR = Decimal("1_000_000")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _as_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _discount(pricing: dict | None) -> Decimal:
    """读取模型级折扣倍数（默认 1 无折扣；<=0 视为无效回退到 1）。"""
    if not isinstance(pricing, dict):
        return Decimal("1")
    discount = _as_decimal(pricing.get("discount"))
    return discount if discount > 0 else Decimal("1")


def normalize_token_usage(usage: dict | None) -> dict[str, int]:
    """归一化 token 用量键：兼容 prompt_tokens/completion_tokens 命名。"""
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0}

    def _int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    return {"input_tokens": _int(input_tokens), "output_tokens": _int(output_tokens)}


def compute_text_cost(usage: dict | None, pricing: dict | None) -> Decimal:
    if not isinstance(pricing, dict) or pricing.get("type") != "text":
        return Decimal("0")
    tokens = normalize_token_usage(usage)
    input_price = _as_decimal(pricing.get("input_price_per_1m"))
    output_price = _as_decimal(pricing.get("output_price_per_1m"))
    cache_price = _as_decimal(pricing.get("cache_input_price_per_1m"))
    cache_tokens = 0
    if isinstance(usage, dict):
        cache_tokens = _as_int(usage.get("cache_read_tokens"))
        if not cache_tokens and isinstance(usage.get("calls"), list):
            cache_tokens = sum(
                _as_int(call.get("usage", {}).get("cache_read_tokens"))
                for call in usage["calls"] if isinstance(call, dict)
            )
    has_cache_price = pricing.get("cache_input_price_per_1m") is not None and cache_price >= 0
    cache_tokens = min(tokens["input_tokens"], max(0, cache_tokens)) if has_cache_price else 0
    full_price_input_tokens = tokens["input_tokens"] - cache_tokens
    cost = (
        (Decimal(full_price_input_tokens) / _TOKEN_DIVISOR) * input_price
        + (Decimal(cache_tokens) / _TOKEN_DIVISOR) * cache_price
        + (Decimal(tokens["output_tokens"]) / _TOKEN_DIVISOR) * output_price
    )
    return _money(cost * _discount(pricing))


def image_price_tier(pricing, selection):
    if not pricing or pricing.get("billing_unit") != "pixel_tier":
        return selection.clarity
    width, height = map(int, selection.provider_size.split("x"))
    pixels = width * height
    prices = pricing.get("prices") or {}
    if "single_low" in prices:
        return "single_low" if pixels <= 2_610_000 else "single_high"
    if pixels > 4_630_000:
        raise ValueError("图片尺寸超出像素计价范围")
    return "low" if pixels <= 2_610_000 else "high_capped"


def pixel_receipt_cost(usage, pricing):
    counts = usage.get("output_tier_counts")
    inputs = usage.get("input_image_count")
    if not isinstance(counts, dict) or not counts or type(inputs) is not int or inputs < 0:
        raise ValueError("Incomplete pixel-tier image usage")
    prices = pricing.get("prices") or {}
    for tier, count in counts.items():
        if tier not in prices or type(count) is not int or count < 0:
            raise ValueError("Invalid output tier or count")
    total_count = sum(counts.values())
    if total_count < 1 or usage.get("image_count", total_count) != total_count:
        raise ValueError("Inconsistent output image count")
    return sum(compute_image_cost(count, tier, pricing) for tier, count in counts.items()) + compute_input_image_cost(inputs, pricing)


def compute_image_cost(image_count: int, clarity: str | None, pricing: dict | None) -> Decimal:
    if not isinstance(pricing, dict) or pricing.get("type") != "image":
        return Decimal("0")
    prices = pricing.get("prices") or {}
    if not isinstance(prices, dict) or clarity not in prices:
        return Decimal("0")
    return _money(_as_decimal(prices[clarity]) * Decimal(int(image_count or 0)) * _discount(pricing))


def compute_input_image_cost(input_image_count: int, pricing: dict | None) -> Decimal:
    """图生图输入参考图费用：前 first_free 张免费，超出按 price_per_image 计。"""
    if not isinstance(pricing, dict):
        return Decimal("0")
    input_fee = pricing.get("input_image")
    if not isinstance(input_fee, dict):
        return Decimal("0")
    first_free = _as_int(input_fee.get("first_free"))
    price_per_image = _as_decimal(input_fee.get("price_per_image"))
    billable = max(0, int(input_image_count or 0) - first_free)
    return _money(Decimal(billable) * price_per_image * _discount(pricing))


# 每个分辨率档位每秒的 token 数（帧率固定 24fps）：
# 宽 × 高 × 24 / 1024。480p 为 864×496，720p 为 1280×720，1080p 为 1920×1080，
# 4k 为 3840×2160。用这些系数反算文档「价格示例」的元/个 完全吻合。
TOKENS_PER_SECOND: dict[str, int] = {
    "480p": 10044,
    "720p": 21600,
    "1080p": 48600,
    "4k": 194400,
}


def compute_video_cost(
    seconds: float,
    resolution: str | None,
    pricing: dict | None,
    input_video_seconds: float = 0.0,
    has_video_reference: bool = False,
    input_image_count: int = 0,
) -> Decimal:
    """按配置的 token/秒策略计算输出视频及输入素材费用。

    ``billing_unit=second`` 时，输出视频与输入参考视频分别按秒计费；
    其余配置保持 Seedance 的元/百万 token 兼容算法。
    """
    if not isinstance(pricing, dict) or pricing.get("type") != "video":
        return Decimal("0")
    output_prices = pricing.get("prices")
    if not isinstance(output_prices, dict) or resolution not in output_prices:
        return Decimal("0")
    reference_prices = pricing.get("video_reference_prices") or output_prices
    if not isinstance(reference_prices, dict):
        reference_prices = output_prices
    image_cost = compute_input_image_cost(input_image_count, pricing)
    if pricing.get("billing_unit") == "second":
        output_cost = _as_decimal(output_prices[resolution]) * _as_decimal(seconds)
        input_video_cost = Decimal("0")
        if has_video_reference and resolution in reference_prices:
            input_video_cost = (
                _as_decimal(reference_prices[resolution])
                * _as_decimal(input_video_seconds)
            )
        return _money((output_cost + input_video_cost) * _discount(pricing) + image_cost)

    prices = reference_prices if has_video_reference else output_prices
    if resolution not in prices:
        return Decimal("0")
    tokens_per_second = TOKENS_PER_SECOND.get(resolution, 0)
    total_seconds = _as_decimal(seconds) + _as_decimal(input_video_seconds)
    tokens = Decimal(tokens_per_second) * total_seconds
    token_cost = (
        _as_decimal(prices[resolution])
        * tokens
        / Decimal("1_000_000")
        * _discount(pricing)
    )
    return _money(token_cost + image_cost)


def compute_asr_cost(seconds: float, pricing: dict | None) -> Decimal:
    """按配置的单价计算语音识别（ASR）费用。

    默认 pricing 格式：
    {"type": "asr", "currency": "CNY", "billing_unit": "minute", "price_per_minute": 0.015}
    按实际秒数折算分钟：seconds / 60。
    """
    if not isinstance(pricing, dict) or pricing.get("type") != "asr":
        return Decimal("0")
    price_per_minute = _as_decimal(pricing.get("price_per_minute"))
    minutes = _as_decimal(seconds) / Decimal("60")
    cost = minutes * price_per_minute
    return _money(cost * _discount(pricing))
