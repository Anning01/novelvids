from fastapi import HTTPException

from prompts.styles import get_style
from services.video.capabilities import CAPABILITIES, COMMON_RATIOS


def project_aspect_ratios() -> tuple[str, ...]:
    """返回有确定画幅的项目级比例，复用视频能力注册表。"""
    supported = {
        ratio
        for capabilities in CAPABILITIES.values()
        for ratio in capabilities.aspect_ratios
    }
    return tuple(
        ratio for ratio in COMMON_RATIOS if ratio != "adaptive" and ratio in supported
    )


def project_resolutions() -> tuple[str, ...]:
    """按模型注册顺序返回所有项目级清晰度选项。"""
    values: list[str] = []
    for capabilities in CAPABILITIES.values():
        for resolution in capabilities.resolutions:
            if resolution not in values:
                values.append(resolution)
    return tuple(values)


def validate_project_config(
    data: dict,
    *,
    current=None,
) -> dict:
    """校验并规范化项目默认值；返回可直接持久化的新字典。"""
    normalized = dict(data)
    blank_custom_style = False
    if "custom_style_prompt" in normalized:
        custom = normalized["custom_style_prompt"]
        stripped = custom.strip() if custom else ""
        blank_custom_style = custom is not None and not stripped
        normalized["custom_style_prompt"] = stripped or None

    aspect_ratio = normalized.get(
        "aspect_ratio",
        getattr(current, "aspect_ratio", None),
    )
    resolution = normalized.get(
        "resolution",
        getattr(current, "resolution", None),
    )
    style_key = normalized.get("style_key", getattr(current, "style_key", None))
    custom_style_prompt = normalized.get(
        "custom_style_prompt",
        getattr(current, "custom_style_prompt", None),
    )

    if aspect_ratio is not None and aspect_ratio not in project_aspect_ratios():
        raise HTTPException(status_code=422, detail="项目画面比例不受支持")
    if resolution is not None and resolution not in project_resolutions():
        raise HTTPException(status_code=422, detail="项目清晰度不受支持")
    if style_key and custom_style_prompt:
        raise HTTPException(status_code=422, detail="系统风格与自定义风格只能选择一种")
    if style_key and get_style(style_key) is None:
        raise HTTPException(status_code=422, detail="视觉风格不存在")
    if blank_custom_style:
        raise HTTPException(status_code=422, detail="自定义风格不能为空")
    return normalized
