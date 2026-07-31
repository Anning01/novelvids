from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from controllers.asset import asset_controller
from controllers.chapter import chapter_controller
from controllers.novel import novel_controller
from controllers.scene import scene_controller
from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig, GeneralConfig
from models.novel import Novel
from schemas.scene import SoraScenePromptConfig
from services.extraction.extractor import PersonExtractor, PersonList
from services.project_analysis.handler import BookAnalysis, _cover_prompt
from services.reference.generator import build_sora_compatible_prompt
from services.storyboard.handler import format_storyboard_prompt
from utils.enums import AiTaskTypeEnum, AssetTypeEnum


def _shot() -> SoraScenePromptConfig:
    return SoraScenePromptConfig(
        sequence=1,
        description="晨雾中的会面",
        duration="4s",
        visual_prose="晨雾笼罩石桥。",
        actions=["0.0s-4.0s: @李舟缓步前行。"],
        format_and_look="180° 快门，细颗粒。",
        lenses_and_filtration="35mm 球面镜头。",
        lighting_and_atmosphere="柔和逆光与薄雾。",
        grade_and_palette="低饱和青灰色。",
        camera_movement="缓慢推进。",
        sound_design="环境水声，-20 LUFS。",
    )


def test_reference_prompt_supports_chinese_and_english():
    data = {
        "type": "person",
        "canonical_name": "李舟",
        "base_traits": "青年，黑发，深色斗篷",
        "description": "沉着的旅人",
    }

    chinese = build_sora_compatible_prompt(data, "zh")
    english = build_sora_compatible_prompt(data, "en")

    assert "上半身正面平视特写" in chinese
    assert "全身三视图" in chinese
    assert "正面全身、侧面全身、背面全身" in chinese
    assert "upper-body, front-facing, eye-level close-up" in english
    assert "full-body three-view turnaround" in english
    assert "front, side, and back full-body views" in english
    assert "沉着的旅人" not in chinese
    assert "沉着的旅人" not in english
    assert "Anime" not in english
    assert "二次元" not in chinese


def test_reference_prompt_supports_group_scene_and_prop_layouts():
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

    chinese_group = build_sora_compatible_prompt(group_data, "zh")
    english_group = build_sora_compatible_prompt(group_data, "en")
    chinese_scene = build_sora_compatible_prompt(scene_data, "zh")
    english_scene = build_sora_compatible_prompt(scene_data, "en")
    chinese_prop = build_sora_compatible_prompt(prop_data, "zh")
    english_prop = build_sora_compatible_prompt(prop_data, "en")

    assert chinese_group == group_data["base_traits"]
    assert english_group == group_data["base_traits"]
    assert group_data["description"] not in chinese_group

    assert chinese_scene.startswith("生成四宫格画面，展示同一个场景中的四个不同视角")
    assert all(view in chinese_scene for view in ("正视图", "俯视图", "背视图", "侧视图"))
    assert "four-panel environment reference sheet" in english_scene
    assert "high-angle aerial view" in english_scene
    assert scene_data["description"] not in chinese_scene

    assert chinese_prop == "【道具描述】氧化铜外壳，黑色刻度盘"
    assert english_prop == "[Prop description] 氧化铜外壳，黑色刻度盘"
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


def test_reference_prompt_uses_requested_aspect_ratio():
    prompt = build_sora_compatible_prompt(
        {
            "type": "scene",
            "canonical_name": "山谷",
            "aspect_ratio": "21:9",
        },
        "zh",
    )

    assert "21:9" in prompt


def test_storyboard_prompt_labels_follow_language():
    chinese = format_storyboard_prompt(_shot(), "zh")
    english = format_storyboard_prompt(_shot(), "en")

    assert chinese.startswith("视觉描述:")
    assert "\n运镜:" in chinese
    assert english.startswith("Visual Prose:")
    assert "\nCamera Movement:" in english
    assert "['" not in chinese


@pytest.mark.asyncio
async def test_extractor_requests_configured_visual_language():
    completion = SimpleNamespace()
    mocked_completion = AsyncMock(return_value=(PersonList(persons=[]), completion))
    with patch(
        "services.extraction.extractor.create_json_completion",
        mocked_completion,
    ):
        extractor = PersonExtractor(
            client=SimpleNamespace(),
            model="test-model",
            prompt_language="zh",
        )
        await extractor.extract("李舟走上石桥。", chapter_number=1)

    messages = mocked_completion.await_args.kwargs["messages"]
    assert "简体中文" in messages[0]["content"]
    assert "base_traits 必须使用简体中文" in messages[1]["content"]


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
        is_active=True,
    )

    tasks = [
        await chapter_controller.extract(chapter.id),
        await scene_controller.generate(chapter.id),
        await asset_controller.reference(asset.id),
        await novel_controller.analyze(novel.id),
    ]

    assert {task.request_params["prompt_language"] for task in tasks} == {"zh"}
