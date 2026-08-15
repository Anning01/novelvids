import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from controllers.asset import asset_controller
from controllers.chapter import chapter_controller
from controllers.novel import novel_controller
from controllers.scene import scene_controller
from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig, GeneralConfig
from models.novel import Novel
from prompts.extraction import (
    GROUP_PORTRAIT_TRAIT_LABELS,
    SINGLE_CHARACTER_TRAIT_LABELS,
)
from prompts.reference import render_default_asset_prompt
from prompts.storyboard import format_storyboard_prompt
from schemas.scene import SoraScenePromptConfig
from services.extraction.context import (
    ChapterExtractionInput,
    ExtractionContext,
    NovelExtractionMetadata,
)
from services.extraction.extractor import AssetExtractionResult, AssetExtractor, Person
from services.extraction.messages import ExtractionMessageBuilder
from services.project_analysis.handler import BookAnalysis, _cover_prompt
from services.reference.generator import build_sora_compatible_prompt
from utils.enums import AiTaskTypeEnum, AssetTypeEnum


SAFE_EXTRACTION_ERROR = (
    "资产提取模型调用失败"
    "（错误代码：asset_extraction_gateway_error）"
)


def _shot() -> SoraScenePromptConfig:
    return SoraScenePromptConfig(
        sequence=1,
        description="晨雾中的会面",
        duration="4s",
        shot_size_and_camera="中景正面机位",
        visual_style="冷峻写实风，轻微柔焦",
        effect_restrictions=["禁止廉价发光粒子"],
        time_setting="清晨，阴天",
        environment="石桥被晨雾包围，环境安静",
        spatial_relationships="李舟位于桥中央，镜头在桥头正对人物",
        visual_prose="晨雾笼罩石桥。",
        actions=["0.0s-4.0s: @李舟缓步前行。"],
        format_and_look="180° 快门，细颗粒。",
        lenses_and_filtration="35mm 球面镜头。",
        lighting_and_atmosphere="柔和逆光与薄雾。",
        grade_and_palette="低饱和青灰色。",
        camera_movement="缓慢推进。",
        sound_design="环境水声，-20 LUFS。",
        dialogue=[],
        transition="以人物前进方向承接下一镜头。",
        allowed_effects=["自然雾气"],
    )


@pytest.mark.parametrize(
    ("prompt_language", "language_name"),
    [("zh", "简体中文"), ("en", "英文")],
)
def test_extraction_system_rules_keep_fixed_labels_in_both_languages(
    prompt_language: str,
    language_name: str,
):
    context = ExtractionContext(
        novel=NovelExtractionMetadata(
            name="语言测试",
            author=None,
            description=None,
            tags=(),
            story_outline=None,
            project_type=None,
            project_setting=None,
        ),
        assets=(),
        chapter=ChapterExtractionInput(
            id=1,
            number=1,
            name="起点",
            content="唯一章节事实。",
        ),
    )

    messages = ExtractionMessageBuilder().build(context, prompt_language)
    system_prompt = messages[0]["content"]

    assert f"目标提示词语言：{language_name}" in system_prompt
    assert f"base_traits 必须使用{language_name}" in system_prompt
    assert all(label in system_prompt for label in SINGLE_CHARACTER_TRAIT_LABELS)
    assert all(label in system_prompt for label in GROUP_PORTRAIT_TRAIT_LABELS)
    assert "唯一章节事实。" not in system_prompt
    assert "严格返回以下 JSON" not in system_prompt
    assert "```json" not in system_prompt
    assert "必须返回空数组" not in system_prompt
    assert "为空也必须返回空数组" not in system_prompt


def test_default_reference_prompt_supports_chinese_and_english():
    chinese = render_default_asset_prompt(
        asset_type="person",
        visual_traits="青年，黑发，深色斗篷",
        prompt_language="zh",
    )
    english = render_default_asset_prompt(
        asset_type="person",
        visual_traits="young man, black hair, dark cloak",
        prompt_language="en",
    )

    assert "上半身正面平视特写" in chinese
    assert "全身三视图" in chinese
    assert "正面全身、侧面全身、背面全身" in chinese
    assert "upper-body, front-facing, eye-level close-up" in english
    assert "full-body three-view turnaround" in english
    assert "front, side, and back full-body views" in english
    assert "Anime" not in english
    assert "二次元" not in chinese
    assert "水印" in chinese
    assert "watermarks" in english


def test_default_reference_prompt_supports_group_scene_and_prop_layouts():
    group_data = {
        "type": "person",
        "canonical_name": "调查小队",
        "base_traits": "李舟居中，林遥站在左侧，顾衡站在右侧",
        "description": "三人是长期协作的伙伴",
        "metadata": {"reference_layout": "group_portrait"},
    }
    scene_data = {
        "type": "scene",
        "canonical_name": "石桥",
        "base_traits": "青石桥面，薄雾，河岸柳树",
        "description": "清晨，无人",
    }
    prop_data = {
        "type": "item",
        "canonical_name": "铜制罗盘",
        "base_traits": "氧化铜外壳，黑色刻度盘",
        "description": "边缘有一道细小裂纹",
    }

    chinese_group = render_default_asset_prompt(
        asset_type="person",
        visual_traits=group_data["base_traits"],
        prompt_language="zh",
        reference_layout="group_portrait",
    )
    english_group = render_default_asset_prompt(
        asset_type="person",
        visual_traits=group_data["base_traits"],
        prompt_language="en",
        reference_layout="group_portrait",
    )
    chinese_scene = render_default_asset_prompt(
        asset_type="scene",
        visual_traits=scene_data["base_traits"],
        prompt_language="zh",
    )
    english_scene = render_default_asset_prompt(
        asset_type="scene",
        visual_traits=scene_data["base_traits"],
        prompt_language="en",
    )
    chinese_prop = render_default_asset_prompt(
        asset_type="item",
        visual_traits=prop_data["base_traits"],
        prompt_language="zh",
    )
    english_prop = render_default_asset_prompt(
        asset_type="item",
        visual_traits=prop_data["base_traits"],
        prompt_language="en",
    )

    assert chinese_group == group_data["base_traits"]
    assert english_group == group_data["base_traits"]
    assert group_data["description"] not in chinese_group

    assert chinese_scene.startswith("生成四宫格画面，展示同一个场景中的四个不同视角")
    assert all(view in chinese_scene for view in ("正视图", "俯视图", "背视图", "侧视图"))
    assert "four-panel environment reference sheet" in english_scene
    assert "high-angle aerial view" in english_scene
    assert scene_data["description"] not in chinese_scene
    assert "水印" in chinese_scene
    assert "watermarks" in english_scene

    assert chinese_prop.startswith("【道具描述】氧化铜外壳，黑色刻度盘")
    assert english_prop.startswith("[Prop description] 氧化铜外壳，黑色刻度盘")
    assert "水印" in chinese_prop
    assert "watermarks" in english_prop
    assert prop_data["description"] not in chinese_prop


def test_reference_prompt_keeps_a_complete_manual_override_verbatim():
    complete_prompt = (
        "任务：完成角色的上半身正面平视特写和该角色的全身三视图，"
        "这是用户手动修改后的完整提示词。"
    )
    prompt = build_sora_compatible_prompt(
        {
            "type": "person",
            "base_traits": complete_prompt,
            "description": "不应追加的剧情描述",
        },
        "zh",
    )

    assert prompt == complete_prompt


def test_reference_generation_uses_custom_database_prompt_verbatim():
    custom_prompt = "单人半身肖像，正面看向镜头，不要三视图，暖灰背景。"

    assert build_sora_compatible_prompt(
        {"type": "person", "base_traits": custom_prompt},
        "zh",
    ) == custom_prompt


def test_default_reference_prompt_uses_requested_aspect_ratio():
    prompt = render_default_asset_prompt(
        asset_type="scene",
        visual_traits="山谷与河流",
        aspect_ratio="21:9",
        prompt_language="zh",
    )

    assert "21:9" in prompt


def test_storyboard_prompt_uses_professional_chinese_structure():
    chinese = format_storyboard_prompt(_shot(), "zh")
    english = format_storyboard_prompt(_shot(), "en")

    assert chinese.startswith("【禁止项】")
    assert "【风格定调】" in chinese
    assert "【角色 / 道具 / 场景引用】" in chinese
    assert "【全局前置条件】" in chinese
    assert "【镜头描述】" in chinese
    assert "【镜头1 · @{镜头时长:4s} · 中景正面机位" in chinese
    assert "【转场方式】" in chinese
    assert "【特效规范】" in chinese
    assert "总时长：@{镜头时长:4s}" in chinese
    assert english == chinese
    assert "['" not in chinese


@pytest.mark.asyncio
async def test_asset_extractor_forwards_prepared_messages_once():
    messages = [
        {"role": "system", "content": "rules-marker"},
        {"role": "user", "content": "novel-marker"},
        {"role": "user", "content": "assets-marker"},
        {"role": "user", "content": "chapter-marker"},
    ]
    completion = SimpleNamespace()
    mocked_completion = AsyncMock(
        return_value=(
            AssetExtractionResult(persons=[], scenes=[], items=[]),
            completion,
        )
    )
    with patch(
        "services.extraction.extractor.create_json_completion",
        mocked_completion,
    ):
        extractor = AssetExtractor(
            client=SimpleNamespace(),
            model="test-model",
            supports_json_output=True,
        )
        result = await extractor.extract(messages)

    assert isinstance(result, AssetExtractionResult)
    mocked_completion.assert_awaited_once()
    assert mocked_completion.await_args.kwargs["messages"] == messages
    assert (
        mocked_completion.await_args.kwargs["response_model"]
        is AssetExtractionResult
    )
    assert mocked_completion.await_args.kwargs["supports_json_output"] is True


def test_asset_extraction_result_requires_all_three_collections():
    with pytest.raises(ValidationError):
        AssetExtractionResult.model_validate({})


@pytest.mark.parametrize("missing", ["persons", "scenes", "items"])
def test_asset_extraction_result_rejects_any_missing_collection(missing: str):
    payload = {"persons": [], "scenes": [], "items": []}
    payload.pop(missing)

    with pytest.raises(ValidationError):
        AssetExtractionResult.model_validate(payload)


def test_asset_extractor_requires_explicit_model():
    with pytest.raises(TypeError):
        AssetExtractor(client=SimpleNamespace())


def _pydantic_error_with_marker(marker: str) -> ValidationError:
    try:
        Person.model_validate({"name": marker})
    except ValidationError as error:
        return error
    raise AssertionError("expected invalid person payload")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_factory",
    [
        lambda marker: RuntimeError(f"provider response: {marker}"),
        lambda marker: json.JSONDecodeError(
            f"invalid json: {marker}",
            f"input_value={marker}",
            0,
        ),
        _pydantic_error_with_marker,
    ],
)
async def test_asset_extractor_maps_gateway_failures_without_leaking_content(
    error_factory,
):
    marker = "secret-provider-marker"
    mocked_completion = AsyncMock(side_effect=error_factory(marker))
    extractor = AssetExtractor(client=SimpleNamespace(), model="test-model")

    with (
        patch(
            "services.extraction.extractor.create_json_completion",
            mocked_completion,
        ),
        pytest.raises(RuntimeError) as captured,
    ):
        await extractor.extract(
            [{"role": "user", "content": f"chapter={marker}"}]
        )

    assert type(captured.value).__name__ == "AssetExtractionGatewayError"
    assert str(captured.value) == SAFE_EXTRACTION_ERROR
    assert marker not in repr(captured.value)
    assert captured.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_asset_extractor_does_not_swallow_cancelled_error():
    extractor = AssetExtractor(client=SimpleNamespace(), model="test-model")
    with patch(
        "services.extraction.extractor.create_json_completion",
        new=AsyncMock(side_effect=asyncio.CancelledError()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await extractor.extract([])


def test_person_visual_traits_reject_placeholder_values():
    placeholder_traits = """时代基底: 现代
国家/朝代: 中国
人种: 东亚人
类型基底: 写实
脸型: None
发型: 无
耳饰: 未提及
身材: 未知
头身比: 无/None
上身着装: 无法确认
下身着装: unknown
鞋子: not mentioned
性别: 男性
年龄: 青年"""

    with pytest.raises(ValidationError, match="不得使用占位值"):
        Person(
            name="宫平",
            description="小说人物",
            base_traits=placeholder_traits,
        )


def test_project_cover_prompt_supports_both_languages():
    novel = SimpleNamespace(name="山海归途")
    analysis = BookAnalysis(
        book_types=["奇幻"],
        story_outline="一名旅人寻找归途。",
        key_characters=[],
    )

    assert _cover_prompt(novel, analysis, "zh").startswith("为小说")
    assert _cover_prompt(novel, analysis, "en").startswith("Create a vertical")


@pytest.mark.asyncio
async def test_all_generation_tasks_snapshot_the_global_language():
    await GeneralConfig.create(id=1, prompt_language="zh")
    novel = await Novel.create(name="语言测试", content="第1章 起点\n李舟走上石桥。")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第1章 起点",
        content="李舟走上石桥。",
    )
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李舟",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[
            AiTaskTypeEnum.extraction.value,
            AiTaskTypeEnum.storyboard.value,
        ],
        name="language-llm",
        base_url="https://llm.example.com",
        api_key="secret",
        model="test-llm",
        is_active=True,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        task_types=[AiTaskTypeEnum.reference_image.value],
        name="language-image",
        base_url="https://image.example.com",
        api_key="secret",
        model="test-image",
        image_model_type="gpt_image_2",
        is_active=True,
    )

    tasks = [
        await chapter_controller.extract(chapter.id),
        await scene_controller.generate(chapter.id),
        await asset_controller.reference(asset.id),
        await novel_controller.analyze(novel.id),
    ]

    assert {task.request_params["prompt_language"] for task in tasks} == {"zh"}
