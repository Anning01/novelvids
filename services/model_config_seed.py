"""默认模型配置初始化：首次部署无模型时自动创建（未启动、空 key）。"""

import logging

from models.config import AiModelConfig
from services.billing.catalog import (
    IMAGE_PRICING,
    LLM_PRICING,
    VIDEO_PRICING,
)
from utils.enums import AiTaskTypeEnum

logger = logging.getLogger(__name__)

_EXTRACTION = AiTaskTypeEnum.extraction.value
_STORYBOARD = AiTaskTypeEnum.storyboard.value
_PROJECT_ANALYSIS = AiTaskTypeEnum.project_analysis.value
_REFERENCE_IMAGE = AiTaskTypeEnum.reference_image.value
_VIDEO = AiTaskTypeEnum.video.value

_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_LEGACY_MINIMAX_H3_PLACEHOLDER_PRICING = {
    "type": "video",
    "currency": "CNY",
    "prices": {"768P": 0.0, "2K": 0.0},
    "video_reference_prices": {"768P": 0.0, "2K": 0.0},
}


def _image_spec(name: str, model: str, model_type: str) -> dict:
    return {
        "name": name,
        "task_type": _REFERENCE_IMAGE,
        "task_types": [_REFERENCE_IMAGE],
        "base_url": _ARK_BASE_URL,
        "api_key": "",
        "model": model,
        "api_protocol": "volcengine_ark",
        "image_model_type": model_type,
        "pricing": IMAGE_PRICING[model_type],
    }


def _video_spec(
    name: str,
    model: str,
    model_type: str,
    *,
    base_url: str = _ARK_BASE_URL,
    api_protocol: str = "volcengine_ark",
) -> dict:
    return {
        "name": name,
        "task_type": _VIDEO,
        "task_types": [_VIDEO],
        "base_url": base_url,
        "api_key": "",
        "model": model,
        "api_protocol": api_protocol,
        "video_model_type": model_type,
        "pricing": VIDEO_PRICING[model_type],
    }


DEFAULT_MODELS: list[dict] = [
    {
        "name": "deepseek",
        "task_type": _EXTRACTION,
        "task_types": [_EXTRACTION, _STORYBOARD, _PROJECT_ANALYSIS],
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-v4-pro",
        "api_protocol": "openai_compatible",
        "pricing": {"type": "text", "currency": "CNY", **LLM_PRICING["deepseek-v4-pro"]},
    },
    _image_spec("doubao-seedream-5-0-pro", "doubao-seedream-5-0-pro-260628", "seedream_5_pro"),
    _image_spec("doubao-seedream-5-0-lite", "doubao-seedream-5-0-260128", "seedream_5_lite"),
    _video_spec("doubao-seedance-2.0", "doubao-seedance-2-0-260128", "seedance_2"),
    _video_spec("doubao-seedance-2-0-fast", "doubao-seedance-2-0-fast-260128", "seedance_2_fast"),
    _video_spec("doubao-seedance-2-0-mini", "doubao-seedance-2-0-mini-260615", "seedance_2_mini"),
    _video_spec("doubao-seedance-2.5", "doubao-seedance-2-5-260817", "seedance_2_5"),
    _video_spec(
        "minimax-h3",
        "MiniMax-H3",
        "minimax_h3",
        base_url="https://api.minimaxi.com",
        api_protocol="minimax",
    ),
    _video_spec(
        "wan3",
        "wan3.0-video",
        "wan_3",
        base_url="https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com",
        api_protocol="dashscope",
    ),
]


async def ensure_model_config_seed_data() -> int:
    """首次部署无模型时创建默认模型（未启动、空 key），按名称幂等。"""
    existing_names = {config.name for config in await AiModelConfig.all()}
    created = 0
    for spec in DEFAULT_MODELS:
        if spec["name"] in existing_names:
            continue
        await AiModelConfig.create(**spec, is_active=False)
        created += 1
    legacy_minimax = await AiModelConfig.filter(video_model_type="minimax_h3").all()
    for config in legacy_minimax:
        if config.pricing != _LEGACY_MINIMAX_H3_PLACEHOLDER_PRICING:
            continue
        config.pricing = VIDEO_PRICING["minimax_h3"]
        await config.save(update_fields=["pricing", "updated_at"])
        logger.info("模型配置启动扫描: 已补全 MiniMax H3 刊例价")
    if created:
        logger.info("模型配置启动扫描: 已创建 %s 个默认模型（未启动）", created)
    return created
