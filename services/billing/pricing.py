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
    cost = (
        (Decimal(tokens["input_tokens"]) / _TOKEN_DIVISOR) * input_price
        + (Decimal(tokens["output_tokens"]) / _TOKEN_DIVISOR) * output_price
    )
    return _money(cost * _discount(pricing))


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
