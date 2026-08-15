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
    return _money(cost)


def compute_image_cost(image_count: int, clarity: str | None, pricing: dict | None) -> Decimal:
    if not isinstance(pricing, dict) or pricing.get("type") != "image":
        return Decimal("0")
    prices = pricing.get("prices") or {}
    if not isinstance(prices, dict) or clarity not in prices:
        return Decimal("0")
    return _money(_as_decimal(prices[clarity]) * Decimal(int(image_count or 0)))


def compute_video_cost(seconds: float, resolution: str | None, pricing: dict | None) -> Decimal:
    if not isinstance(pricing, dict) or pricing.get("type") != "video":
        return Decimal("0")
    prices = pricing.get("prices") or {}
    if not isinstance(prices, dict) or resolution not in prices:
        return Decimal("0")
    return _money(_as_decimal(prices[resolution]) * _as_decimal(seconds))
