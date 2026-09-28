"""视觉风格提示词注册表。

每个风格提供两套提示词：
- image_prompt：生图定调 —— 静态画面的材质、光影、色彩与细节要求；
- video_prompt：生视频定调 —— 运动规律、镜头衔接、一致性与时间连续性要求。

本模块仅负责模板与纯渲染函数；业务上下文加载与调用由对应 Service 完成。
"""

from dataclasses import dataclass
from prompts.catalog import catalog, text


AUTO_STYLE_KEY = "auto"
AUTO_STYLE_LABEL = "AI 识别风格"


@dataclass(frozen=True)
class StylePromptSet:
    key: str
    label: str
    image_prompt: str
    video_prompt: str


STYLE_PROMPTS: dict[str, StylePromptSet] = {
    key: StylePromptSet(key, value["label"], value["image"], value["video"])
    for key, value in catalog("styles.json", "zh").items()
}

STYLE_KEYS: tuple[str, ...] = tuple(STYLE_PROMPTS.keys())


def get_style(key: str | None, language: str = "zh") -> StylePromptSet | None:
    """按 key 取风格提示词集；未知 key 返回 None。"""
    if not key:
        return None
    value = catalog("styles.json", language).get(key)
    return (
        StylePromptSet(key, value["label"], value["image"], value["video"])
        if value
        else None
    )


def image_style_suffix(key: str | None, language: str = "zh") -> str:
    """生图风格定调段落；未知 key 返回空串（不注入）。"""
    style = get_style(key, language)
    if style is None:
        return ""
    return text("style_image", language, label=style.label, prompt=style.image_prompt)


def video_style_suffix(key: str | None, language: str = "zh") -> str:
    """生视频风格定调段落；未知 key 返回空串（不注入）。"""
    style = get_style(key, language)
    if style is None:
        return ""
    return text("style_video", language, label=style.label, prompt=style.video_prompt)


def image_project_style_suffix(
    key: str | None,
    custom_style_prompt: str | None,
    language: str = "zh",
) -> str:
    """渲染项目级生图风格；自定义风格由项目配置直接提供。"""
    custom = (custom_style_prompt or "").strip()
    if custom:
        return text("style_custom_image", language, prompt=custom)
    return image_style_suffix(key, language)


def video_project_style_suffix(
    key: str | None,
    custom_style_prompt: str | None,
    language: str = "zh",
) -> str:
    """渲染项目级生视频风格；与生图链路使用同一配置来源。"""
    custom = (custom_style_prompt or "").strip()
    if custom:
        return text("style_custom_video", language, prompt=custom)
    return video_style_suffix(key, language)


def list_styles() -> list[dict]:
    """系统内置风格清单（后端唯一事实来源）。"""
    return [
        {"key": style.key, "label": style.label} for style in STYLE_PROMPTS.values()
    ]


def list_remake_styles() -> list[dict]:
    """重制工坊风格选项；自动识别不注入固定风格 Prompt。"""
    return [
        {"key": AUTO_STYLE_KEY, "label": AUTO_STYLE_LABEL},
        *list_styles(),
    ]
