"""Public labels and tariffs come from active platform-owned configurations."""
from math import isfinite
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum


PUBLIC_KINDS = {
    AiTaskTypeEnum.extraction: "text",
    AiTaskTypeEnum.reference_image: "image",
    AiTaskTypeEnum.storyboard: "text",
    AiTaskTypeEnum.video: "video",
    AiTaskTypeEnum.project_analysis: "text",
    AiTaskTypeEnum.remake_decomposition: "text",
    AiTaskTypeEnum.creation_agent: "text",
    AiTaskTypeEnum.screenplay: "text",
    AiTaskTypeEnum.prompt_optimization: "text",
}


def public_tariff(raw):
    if not isinstance(raw, dict):
        return {}
    def number(v):
        return isinstance(v, (float, int)) and not isinstance(v, bool) and isfinite(v) and v >= 0
    data = {k: v for k,v in raw.items() if k in {
        "input_price_per_1m","cache_input_price_per_1m","output_price_per_1m","price_per_minute","discount"
    } and number(v)}
    data["currency"] = "CNY"
    if raw.get("type") in {"text", "image", "video", "asr", "media_processing"}:
        data["type"] = raw["type"]
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
    rows = await AiModelConfig.filter(scope="official", team_id__isnull=True, is_active=True).exclude(api_protocol="novelvids").order_by("id").values(
        "id","name","created_at","image_model_type","video_model_type","api_protocol","task_type","task_types","pricing","supports_tool_calls","supports_json_output")
    models = []
    for row in rows:
        task_types = row["task_types"] or [row["task_type"]]
        kinds = list(dict.fromkeys(PUBLIC_KINDS[task] for task in task_types if task in PUBLIC_KINDS))
        if not kinds:
            continue
        models.append({
            "id": f"nv-{row['id']}", "name": row["name"], "kinds": kinds,
            "task_types": [task for task in task_types if task in PUBLIC_KINDS],
            "created": int(row["created_at"].timestamp()),
            "image_model_type": row["image_model_type"], "video_model_type": row["video_model_type"],
            "reference_image_urls": bool(row["image_model_type"] and row["api_protocol"] in {"volcengine_ark", "openrouter_compatible"}),
            "pricing": public_tariff(row["pricing"]), "tool_calls": row["supports_tool_calls"],
            "json_output": row["supports_json_output"],
        })
    return models
