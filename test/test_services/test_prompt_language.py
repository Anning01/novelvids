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
from test.visual_fields import trait_labels
from test.visual_fields import GROUP_PORTRAIT_TRAIT_LABELS, SINGLE_CHARACTER_TRAIT_LABELS
from prompts.storyboard import format_storyboard_prompt
from schemas.scene import SoraScenePromptConfig
from services.extraction.context import (
    ChapterExtractionInput,
    ExtractionContext,
    NovelExtractionMetadata,
)
from services.extraction.extractor import AssetExtractionResult, AssetExtractor, Person
from services.extraction.messages import ExtractionMessageBuilder
from services.project_analysis.handler import BookAnalysis
from prompts.project_analysis import render_cover_prompt
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
    [("zh", "简体中文"), ("en", "English")],
)
def test_extraction_rules_use_one_skill_and_explicit_output_language(
    prompt_language: str,
    language_name: str,
):
    from prompts.skill_pack import read_skill
    context = ExtractionContext(novel=NovelExtractionMetadata(name="语言测试", author=None,
        description=None, tags=(), story_outline=None, project_type=None, project_setting=None), assets=(),
        chapter=ChapterExtractionInput(id=1, number=1, name="起点", content="唯一章节事实。"))
    messages = ExtractionMessageBuilder().build(context, prompt_language)
    assert read_skill("assets") in messages[0]["content"]
    assert "language=" + prompt_language in messages[0]["content"]
    assert "唯一章节事实。" not in messages[0]["content"]
    assert json.loads(messages[-1]["content"])["content"] == "唯一章节事实。"


def test_reference_generation_preserves_prompt_language_verbatim():
    for language, value in [("zh", "青年，黑发，深色斗篷"), ("en", "young man, black hair, dark cloak")]:
        assert build_sora_compatible_prompt({"base_traits": value}, language) == value


def test_reference_generation_does_not_inject_type_or_layout_templates():
    for kind, layout, value in [("person", "group_portrait", "三人居中合影"),
                                ("scene", "character_turnaround", "青石桥面，薄雾"),
                                ("item", "character_turnaround", "氧化铜外壳")]:
        for language in ("zh", "en"):
            assert build_sora_compatible_prompt({"base_traits": value, "reference_layout": layout}, language) == value


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


def test_reference_generation_does_not_rewrite_saved_aspect_ratio():
    value = "画幅已写入完整提示词的山谷与河流"
    assert build_sora_compatible_prompt({"base_traits": value, "aspect_ratio": "21:9"}, "zh") == value


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
    assert english.startswith("[Restrictions]")
    assert "[Character / Prop / Location references]" in english
    assert "Total duration: @{镜头时长:4s}" in english
    # Renderer localizes fixed labels without translating stored user prose.
    assert _shot().visual_prose in english
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


def test_new_character_requires_nonempty_visual_prompt_without_fixed_rows():
    from utils.prompt_language import skill_workflow

    assert Person(name="宫平", base_traits="短发青年，深色斗篷").base_traits == "短发青年，深色斗篷"
    token = skill_workflow.set(True)
    try:
        for empty in ("", "  "):
            with pytest.raises(ValidationError, match="must not be empty"):
                Person(name="宫平", base_traits=empty)
    finally:
        skill_workflow.reset(token)


def test_project_cover_prompt_supports_both_languages():
    from prompts.skill_pack import read_skill
    for language in ("zh", "en"):
        value = render_cover_prompt(name="山海归途", book_types=["奇幻"], story_outline="旅人寻找归途。", prompt_language=language)
        assert read_skill("image") in value and "language=" + language in value
        assert "山海归途" in value and "旅人寻找归途。" in value


@pytest.mark.asyncio
async def test_all_generation_tasks_snapshot_the_global_language(configured_creation_agent):
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
