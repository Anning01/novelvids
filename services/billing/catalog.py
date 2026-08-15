"""官方模型计费目录：按模型类型/名称提供默认定价。

价格来源：火山方舟模型服务计费文档（2026-08）。视频为「输入不含视频」的
刊例价（元/秒）；限时折扣需人工调整（见各促销说明）。
"""

from models.config import AiModelConfig

# 文本模型：输入/输出单价（元 / 百万 token）。仅收录一口价模型；
# 分段计费（按输入长度分档）模型暂不收录。
LLM_PRICING: dict[str, dict] = {
    "deepseek-v4-pro": {"input_price_per_1m": 12.00, "output_price_per_1m": 24.00},
    "deepseek-v4-flash": {"input_price_per_1m": 1.00, "output_price_per_1m": 2.00},
    "glm-5.2": {"input_price_per_1m": 8.00, "output_price_per_1m": 28.00},
}

# 生图模型：输出图按清晰度（元/张）；input_image 为图生图输入图费用。
IMAGE_PRICING: dict[str, dict] = {
    "seedream_5_pro": {
        "type": "image",
        "currency": "CNY",
        "prices": {"1K": 0.30, "1.5K": 0.30, "2K": 0.60},
        "input_image": {"first_free": 1, "price_per_image": 0.02},
    },
    "seedream_5_lite": {
        "type": "image",
        "currency": "CNY",
        "prices": {"2K": 0.22, "3K": 0.22, "4K": 0.22},
    },
}

# 视频模型：输出视频按分辨率（元/秒），「输入不含视频」刊例价。
# 注：文档中「输入包含视频」为 token 计费（含输入视频时长），无固定元/秒，
# 故此处不填 video_reference_prices，含视频时回退到 prices。
VIDEO_PRICING: dict[str, dict] = {
    "seedance_2": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 0.46, "720p": 0.99, "1080p": 2.48, "4k": 5.05},
    },
    "seedance_2_fast": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 0.37, "720p": 0.80},
    },
    "seedance_2_mini": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 0.23, "720p": 0.50},
    },
    "seedance_2_5": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 0.67, "720p": 1.51, "1080p": 3.74},
    },
}


def pricing_for(config: AiModelConfig) -> dict | None:
    """返回给定模型的官方默认定价；未知模型返回 None。"""
    if config.image_model_type and config.image_model_type in IMAGE_PRICING:
        return IMAGE_PRICING[config.image_model_type]
    if config.video_model_type and config.video_model_type in VIDEO_PRICING:
        return VIDEO_PRICING[config.video_model_type]
    model = (config.model or "").lower()
    for key, prices in LLM_PRICING.items():
        if key in model:
            return {"type": "text", "currency": "CNY", **prices}
    return None
