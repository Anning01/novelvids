"""视觉风格提示词注册表与注入链路测试。"""

import pytest
from httpx import AsyncClient

from controllers.video import _compose_video_prompt
from prompts.styles import (
    AUTO_STYLE_KEY,
    AUTO_STYLE_LABEL,
    STYLE_KEYS,
    STYLE_PROMPTS,
    get_style,
    image_style_suffix,
    image_project_style_suffix,
    list_remake_styles,
    list_styles,
    video_style_suffix,
    video_project_style_suffix,
)

EXPECTED_KEYS = {
    "realistic-general",
    "realistic-urban",
    "realistic-cinematic",
    "anime-japanese",
    "manhwa-urban",
    "chinese-3d",
    "xianxia-3d",
    "manhwa-2d",
    "otome-2d",
    "chinese-animation-2d",
    "cg",
    "cartoon-3d",
    "cyberpunk-cg",
    "gongbi",
}


def test_registry_covers_all_builtin_styles():
    assert set(STYLE_KEYS) == EXPECTED_KEYS
    assert len(STYLE_PROMPTS) == 14


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_each_style_has_image_and_video_prompts(key):
    style = get_style(key)
    assert style is not None
    assert style.label.strip()
    assert len(style.image_prompt) >= 20
    assert len(style.video_prompt) >= 20
    # 两套提示词内容不同（各司其职）
    assert style.image_prompt != style.video_prompt


def test_suffixes_include_style_label():
    suffix = image_style_suffix("gongbi")
    assert "工笔画" in suffix
    suffix = video_style_suffix("gongbi")
    assert "工笔画" in suffix


def test_unknown_style_renders_empty():
    assert get_style("not-exist") is None
    assert image_style_suffix("not-exist") == ""
    assert video_style_suffix("not-exist") == ""
    assert image_style_suffix(None) == ""
    assert video_style_suffix(None) == ""


def test_custom_project_style_is_injected_without_a_registry_key():
    custom = "低饱和复古胶片，暖色高反差，保留细密颗粒"

    assert custom in image_project_style_suffix(None, custom)
    assert custom in video_project_style_suffix(None, custom)
    assert image_project_style_suffix("gongbi", None) == image_style_suffix("gongbi")
    assert video_project_style_suffix("gongbi", None) == video_style_suffix("gongbi")


def test_list_styles_shape():
    styles = list_styles()
    assert len(styles) == 14
    assert styles[0] == {"key": "realistic-general", "label": "写实通用"}
    assert all(set(item) == {"key", "label"} for item in styles)


def test_remake_styles_prepend_ai_recognition_without_changing_builtin_registry():
    styles = list_remake_styles()

    assert len(styles) == 15
    assert styles[0] == {"key": AUTO_STYLE_KEY, "label": AUTO_STYLE_LABEL}
    assert styles[1:] == list_styles()


def test_video_prompt_composition_appends_style():
    prompt = _compose_video_prompt("女主回头，镜头缓慢推进", [], "anime-japanese")
    assert "女主回头" in prompt
    assert "2D日漫" in prompt

    unchanged = _compose_video_prompt("女主回头", [], None)
    assert unchanged == "女主回头"
    unknown = _compose_video_prompt("女主回头", [], "no-such-style")
    assert unknown == "女主回头"
    custom = _compose_video_prompt("女主回头", [], None, "低饱和复古胶片")
    assert "低饱和复古胶片" in custom


@pytest.mark.asyncio
async def test_reference_generator_injects_style_prompt(monkeypatch):
    """生图链路：style_prompt 追加进最终提示词。"""
    from services.reference import generator

    captured: dict = {}
    async def fake_generate_images(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(generator, "generate_images", fake_generate_images)

    await generator.generate_for_sora_consistency(
        {"base_traits": "一位白发剑客，站姿"},
        base_url="https://x",
        api_key="k",
        model="m",
        style_prompt=image_style_suffix("xianxia-3d"),
    )
    assert "白发剑客" in captured["prompt"]
    assert "3D仙侠" in captured["prompt"]

    # 未设置风格时不追加
    captured.clear()
    await generator.generate_for_sora_consistency(
        {"base_traits": "一位白发剑客，站姿"},
        base_url="https://x",
        api_key="k",
        model="m",
    )
    assert "画面风格遵循" not in captured["prompt"]


@pytest.mark.asyncio
async def test_visual_styles_endpoint(client: AsyncClient):
    """风格清单接口：后端唯一事实来源（vanilla 亦可访问）。"""
    response = await client.get("/api/config/visual-styles")
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    items = response.json()["data"]
    assert len(items) == 14
    assert items[0] == {"key": "realistic-general", "label": "写实通用"}
    assert {"key": "gongbi", "label": "工笔画"} in items


@pytest.mark.asyncio
async def test_novel_style_key_persisted(client: AsyncClient):
    """创建项目时提交 style_key 并持久化。"""
    from models.novel import Novel

    response = await client.post(
        "/api/novel",
        json={"name": "风格项目", "author": "x", "style_key": "chinese-3d"},
    )
    assert response.json()["code"] == 0, response.text
    novel = await Novel.get(name="风格项目")
    assert novel.style_key == "chinese-3d"
