import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from prompts.storyboard import build_storyboard_messages, format_storyboard_prompt
from schemas.scene import SceneEntity, SoraScenePromptConfig, Storyboard
from services.llm.json_output import JsonCompletionTruncatedError
from services.storyboard.chunking import NarrativeChunker
from services.storyboard.generator import generate_storyboard


def _entity() -> SceneEntity:
    return SceneEntity(
        name="郊区小楼",
        aliases=["小楼", "旧宅"],
        description="红砖外墙，窗框斑驳",
        asset_type="场景",
    )


def _shot(sequence: int, title: str = "夜访小楼") -> SoraScenePromptConfig:
    return SoraScenePromptConfig(
        sequence=sequence,
        description=title,
        duration="4s",
        shot_size_and_camera="中景正面机位",
        visual_style="冷色写实悬疑风",
        effect_restrictions=["禁止廉价发光特效"],
        time_setting="深夜，阴天",
        environment="湿冷夜风吹动树影",
        spatial_relationships="小楼居中，人物从画面左侧接近入口",
        visual_prose="@{郊区小楼} 隐没在夜色中。",
        actions=["0.0s-4.0s: 镜头缓慢接近 @{郊区小楼}。"],
        format_and_look="180° 快门，35mm 数字摄影颗粒",
        lenses_and_filtration="35mm 球面镜头，轻微柔焦",
        lighting_and_atmosphere="冷色月光，低照度薄雾",
        grade_and_palette="青灰阴影，低饱和中间调",
        camera_movement="缓慢推镜",
        sound_design="夜风与树叶摩擦声",
        dialogue=[],
        transition="沿推镜方向承接下一镜头",
        allowed_effects=["自然薄雾"],
    )


def test_storyboard_messages_render_language_entities_and_narrative():
    narrative = "夜色里，小楼的窗户忽然亮起。"
    messages = build_storyboard_messages(narrative, [_entity()], "zh")

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "user",
        "user",
    ]
    assert "使用简体中文" in messages[0]["content"]
    assert "郊区小楼" not in messages[0]["content"]
    assert '"canonical_name":"郊区小楼"' in messages[1]["content"]
    assert '"aliases":["小楼","旧宅"]' in messages[1]["content"]
    assert "@{郊区小楼}" in messages[1]["content"]
    assert narrative not in messages[0]["content"]
    assert narrative in messages[2]["content"]
    assert "分镜生成任务" in messages[3]["content"]


@pytest.mark.asyncio
async def test_storyboard_generator_uses_centralized_message_renderer():
    storyboard = Storyboard(shots=[])
    completion = SimpleNamespace(
        model="storyboard-model",
        id="response-id",
        created=1,
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(refusal=None))],
    )
    completion_call = AsyncMock(return_value=(storyboard, completion))

    with patch(
        "services.storyboard.generator.create_json_completion",
        completion_call,
    ):
        result, _metadata = await generate_storyboard(
            client=object(),
            long_text="章节正文",
            entities=[_entity()],
            model="storyboard-model",
            prompt_language="zh",
        )

    assert result == storyboard
    assert completion_call.await_args.kwargs["messages"] == build_storyboard_messages(
        "章节正文",
        [_entity()],
        "zh",
    )


def test_narrative_chunker_splits_long_chapters_on_semantic_boundaries():
    chunks = NarrativeChunker(600).split("第一句。" * 220)

    assert len(chunks) > 1
    assert all(len(chunk) <= 600 for chunk in chunks)
    assert "".join(chunks) == "第一句。" * 220


def test_professional_prompt_renders_only_assets_referenced_by_the_shot():
    unused = SceneEntity(
        name="旧钥匙",
        aliases=[],
        description="黄铜材质，齿槽磨损",
        asset_type="物品",
    )

    prompt = format_storyboard_prompt(
        _shot(1),
        "zh",
        entities=[_entity(), unused],
    )

    assert "场景参考：郊区小楼" in prompt
    assert "场景概念图：郊区小楼。红砖外墙，窗框斑驳" in prompt
    assert "旧钥匙" not in prompt


@pytest.mark.asyncio
async def test_storyboard_generator_uses_fresh_continuation_calls():
    completions = [
        SimpleNamespace(
            model="storyboard-model",
            id=f"response-{index}",
            created=index,
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(refusal=None))],
        )
        for index in (1, 2)
    ]
    completion_call = AsyncMock(
        side_effect=[
            (Storyboard(shots=[_shot(9, "第一批")]), completions[0]),
            (Storyboard(shots=[_shot(1, "第二批")]), completions[1]),
        ]
    )

    with patch(
        "services.storyboard.generator.create_json_completion",
        completion_call,
    ):
        result, metadata = await generate_storyboard(
            client=object(),
            long_text="第一句。" * 1600,
            entities=[_entity()],
            model="storyboard-model",
            prompt_language="zh",
        )

    assert [shot.sequence for shot in result.shots] == [1, 2]
    assert completion_call.await_count == 2
    first_messages = completion_call.await_args_list[0].kwargs["messages"]
    second_messages = completion_call.await_args_list[1].kwargs["messages"]
    assert "分镜生成任务" in first_messages[-1]["content"]
    assert "分镜续写任务" in second_messages[-1]["content"]
    assert '"sequence":1' in second_messages[-1]["content"]
    assert "第一句。" * 20 not in second_messages[0]["content"]
    assert metadata["batch_count"] == 2


@pytest.mark.asyncio
async def test_storyboard_generator_retries_a_truncated_batch_as_smaller_chunks():
    completion = SimpleNamespace(
        model="storyboard-model",
        id="response-id",
        created=1,
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(refusal=None))],
    )
    completion_call = AsyncMock(
        side_effect=[
            JsonCompletionTruncatedError("truncated"),
            (Storyboard(shots=[_shot(1)]), completion),
            (Storyboard(shots=[_shot(1)]), completion),
        ]
    )

    with patch(
        "services.storyboard.generator.create_json_completion",
        completion_call,
    ):
        result, metadata = await generate_storyboard(
            client=object(),
            long_text="一句话。" * 250,
            entities=[_entity()],
            model="storyboard-model",
        )

    assert completion_call.await_count == 3
    assert len(result.shots) == 2
    assert metadata["batch_count"] == 2


def test_storyboard_services_do_not_inline_large_prompt_templates():
    project_root = Path(__file__).resolve().parents[2]
    service_paths = (
        project_root / "services/storyboard/generator.py",
        project_root / "services/storyboard/handler.py",
    )

    for service_path in service_paths:
        syntax_tree = ast.parse(service_path.read_text(encoding="utf-8"))
        large_literals = [
            node.value
            for node in ast.walk(syntax_tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and len(node.value) >= 400
        ]
        assert not large_literals, (
            f"{service_path.relative_to(project_root)} 中存在大段内联文本；"
            "Prompt 模板必须放入 prompts/。"
        )
