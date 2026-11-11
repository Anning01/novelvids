"""Public labels and tariffs come from active platform-owned configurations."""
from math import isfinite
from models.config import AiModelConfig


def public_tariff(raw):
    if not isinstance(raw, dict):
        return {}
    def number(v):
        return isinstance(v, (float, int)) and not isinstance(v, bool) and isfinite(v) and v >= 0
    data = {k: v for k,v in raw.items() if k in {
        "input_price_per_1m","cache_input_price_per_1m","output_price_per_1m","price_per_minute","discount"
    } and number(v)}
    data["currency"] = "CNY"
    if raw.get("billing_unit") in {"token", "second", "minute"}:
        data["billing_unit"] = raw["billing_unit"]
    for k in ("prices","video_reference_prices"):
        if isinstance(raw.get(k), dict):
            data[k] = {str(tier):v for tier,v in raw[k].items() if number(v)}
    if isinstance(raw.get("input_image"), dict):
        data["input_image"] = {k:v for k,v in raw["input_image"].items() if k in {"first_free","price_per_image"} and number(v)}
    if isinstance(raw.get("tiers"), list):
        data["tiers"] = [{k:v for k,v in tier.items() if k in {"short_side_max","fps_max","price"} and number(v)}
                         for tier in raw["tiers"] if isinstance(tier, dict)]
    return data


async def model_catalog():
    rows = await AiModelConfig.filter(scope="official", team_id__isnull=True, is_active=True).order_by("id").values(
        "id","name","task_type","task_types","pricing","supports_tool_calls","supports_json_output")
    kinds = {2:"image", 4:"video", 8:"media_processing", 9:"asr"}
    return [{"id": f"nv-{r['id']}", "name":r["name"],
             "kinds":list(dict.fromkeys(kinds.get(t, "text") for t in (r["task_types"] or [r["task_type"]]))),
             "pricing":public_tariff(r["pricing"]), "tool_calls":r["supports_tool_calls"], "json_output":r["supports_json_output"]}
            for r in rows]
