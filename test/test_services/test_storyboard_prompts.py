import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from prompts.skill_pack import render_skill
from prompts.storyboard import (
    entity_reference_names,
    format_storyboard_prompt,
    normalized_storyboard_reference_fields,
    referenced_entities,
)
from schemas.scene import SceneEntity, SoraScenePromptConfig, Storyboard
from services.storyboard.strategies import storyboard_strategy_factory




def _entity() -> SceneEntity:
    return SceneEntity(
        name="郊区小楼",
        aliases=["小楼", "旧宅"],
        description="红砖外墙，窗框斑驳",
        asset_type="场景",
    )


def test_empty_model_reference_is_removed_without_changing_literal_text_or_speech():
    from prompts.storyboard import normalize_storyboard_reference_text
    entity = SceneEntity(name='木杖', aliases=[], description='古代木杖', asset_type='物品')
    text = '他停在那里，@{} @{木杖}没有抬起。牌上写“@{}”。\n0s-2s: 周砚: 原文@{}保留。'
    result = normalize_storyboard_reference_text(text, [entity])
    assert result == '他停在那里， @{木杖}没有抬起。牌上写“@{}”。\n0s-2s: 周砚: 原文@{}保留。'
    assert normalize_storyboard_reference_text(result, [entity]) == result


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




def test_storyboard_strategy_factory_supports_legacy_name_and_safe_fallback():
    assert storyboard_strategy_factory.resolve("电影化叙事 1.5").key == "cinematic"
    assert storyboard_strategy_factory.resolve("旁白叙事").key == "narration"
    assert storyboard_strategy_factory.resolve("unknown-old-value").key == "cinematic"








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

    assert "场景参考：@{郊区小楼}" in prompt
    assert "场景概念图：@{郊区小楼}。红砖外墙，窗框斑驳" in prompt
    assert "旧钥匙" not in prompt


def test_professional_prompt_normalizes_every_referenced_asset_type():
    person = SceneEntity(
        name="李七夜",
        aliases=["李公子"],
        description="李七夜身穿黑袍",
        asset_type="人物",
    )
    item = SceneEntity(
        name="油纸伞",
        aliases=["旧伞"],
        description="油纸伞的竹骨磨损",
        asset_type="物品",
    )
    scene = _entity()
    shot = _shot(1, "李公子持旧伞走向旧宅")
    shot.visual_prose = "李公子持旧伞站在旧宅门前。"

    prompt = format_storyboard_prompt(shot, "zh", entities=[person, item, scene])

    assert "角色参考：@{李七夜}" in prompt
    assert "角色设定图：@{李七夜}。@{李七夜}身穿黑袍" in prompt
    assert "道具参考：@{油纸伞}" in prompt
    assert "道具概念设计图：@{油纸伞}。@{油纸伞}的竹骨磨损" in prompt
    assert "场景参考：@{郊区小楼}" in prompt
    assert "@{李七夜}持@{油纸伞}站在@{郊区小楼}门前" in prompt


def test_professional_video_prompt_excludes_storyboard_planning_instructions():
    prompt = format_storyboard_prompt(_shot(6), "zh", entities=[_entity()])

    assert "【镜头1 ·" in prompt
    assert "【镜头6 ·" not in prompt
    assert "【独立生成约束】" not in prompt
    assert "本镜头是一次独立的视频生成任务" not in prompt
    assert "不得继承其他镜头" not in prompt
    assert "沿推镜方向承接下一镜头" in prompt

    schema = SoraScenePromptConfig.model_json_schema()["properties"]
    assert "连续性转换为当前镜头内的具体状态" in schema["spatial_relationships"]["description"]
    assert "每个时间段都必须重新写明动作主体" in schema["actions"]["description"]
    assert "与相邻镜头的衔接意图" in schema["transition"]["description"]
    assert "不得只写" in schema["transition"]["description"]


def test_narration_strategy_renders_narration_and_specific_prohibitions():
    shot = _shot(1)
    shot.narration = ["0.0s-1.5s: 旁白（克制）：夜色吞没了最后一盏灯。"]
    shot.dialogue = ["2.0s-3.0s: @{郊区小楼}（低声）：有人吗？"]

    prompt = format_storyboard_prompt(
        shot,
        entities=[_entity()],
        strategy=storyboard_strategy_factory.resolve("narration"),
    )

    assert "【旁白 / 内心 OS】" in prompt
    assert shot.narration[0] in prompt
    core_instruction = prompt.split("【核心生成指令｜高优先级】", 1)[1].split("【详细执行】", 1)[0]
    assert shot.visual_prose in core_instruction
    assert shot.actions[0] in core_instruction
    assert shot.narration[0] in core_instruction
    assert shot.dialogue[0] in core_instruction
    assert shot.sound_design in core_instruction
    assert "【禁止项】\n禁止廉价发光特效" in prompt and shot.sound_design in prompt


def test_primary_generation_instruction_orders_all_voice_tracks_by_time():
    shot = _shot(2)
    shot.narration = ["3.0s-4.0s: 旁白（低声）：门外没有回应。"]
    shot.dialogue = ["1.0s-2.0s: @{郊区小楼}（低声）：有人吗？"]

    prompt = format_storyboard_prompt(
        shot,
        entities=[_entity()],
        strategy=storyboard_strategy_factory.resolve("narration"),
    )
    core_instruction = prompt.split("【核心生成指令｜高优先级】", 1)[1].split("【详细执行】", 1)[0]

    assert core_instruction.index(shot.dialogue[0]) < core_instruction.index(shot.narration[0])
    assert prompt.index("【核心生成指令｜高优先级】") < prompt.index("【详细执行】")


def test_cinematic_strategy_renders_the_shots_own_restrictions():
    prompt = format_storyboard_prompt(_shot(1), entities=[_entity()])

    assert "【禁止项】\n禁止廉价发光特效" in prompt
    assert "无旁白" not in prompt
    assert "无人物内心 OS" not in prompt
    assert "【旁白 / 内心 OS】" not in prompt


def test_entity_reference_names_matches_braced_syntax_and_aliases():
    entity = _entity()
    assert referenced_entities(_shot(1), [entity]) == [entity]
    # 未引用实体不会被匹配
    unused = SceneEntity(
        name="旧钥匙",
        aliases=[],
        description="黄铜材质，齿槽磨损",
        asset_type="物品",
    )
    assert referenced_entities(_shot(1), [entity, unused]) == [entity]
    # 纯文本出现名字但非 @{} 绑定语法时不匹配
    assert entity_reference_names("小楼居中，人物接近入口", [entity]) == []
    # 别名以 @{} 形式出现时匹配
    assert entity_reference_names("他走向 @{小楼}", [entity]) == [entity]


def test_normalized_storyboard_reference_fields_fills_missing_asset_tags():
    person = SceneEntity(
        name="李七夜",
        aliases=["李公子", "他", "少年"],
        description="黑发少年",
        asset_type="人物",
    )
    scene = _entity()
    shot = _shot(1)
    shot.spatial_relationships = "李公子位于画面左侧，小楼位于远处。"
    shot.actions = ["0.0s-2.0s: 李七夜抬手，少年退后。"]
    shot.dialogue = ["李公子（低声）：走吧。"]

    updates = normalized_storyboard_reference_fields(shot, [person, scene])

    assert updates["spatial_relationships"] == "@{李七夜}位于画面左侧，@{郊区小楼}位于远处。"
    assert updates["actions"] == ["0.0s-2.0s: @{李七夜}抬手，少年退后。"]
    assert updates["dialogue"] == ["@{李七夜}（低声）：走吧。"]
    assert "environment" not in updates


def test_normalized_storyboard_reference_fields_is_idempotent_and_longest_first():
    short_name = SceneEntity(
        name="李七",
        aliases=[],
        description="",
        asset_type="人物",
    )
    long_name = SceneEntity(
        name="李七夜",
        aliases=["帝子"],
        description="",
        asset_type="人物",
    )
    shot = _shot(1, "@{李七夜}与帝子并肩，李七留在门外。")

    first_updates = normalized_storyboard_reference_fields(
        shot,
        [short_name, long_name],
    )
    normalized_shot = shot.model_copy(update=first_updates)
    second_updates = normalized_storyboard_reference_fields(
        normalized_shot,
        [short_name, long_name],
    )

    assert first_updates["description"] == "@{李七夜}与@{李七夜}并肩，@{李七}留在门外。"
    assert second_updates == {}


def test_normalized_storyboard_reference_fields_handles_attached_chinese_prose():
    person = SceneEntity(
        name="羽宁",
        aliases=[],
        description="黑发学生",
        asset_type="人物",
    )
    shot = _shot(1, "走出单元楼。@羽宁沿着步道走。")

    updates = normalized_storyboard_reference_fields(shot, [person])

    assert updates["description"] == "走出单元楼。@{羽宁}沿着步道走。"






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


@pytest.mark.parametrize("key", ["cinematic", "narration"])
@pytest.mark.parametrize("language", ["zh", "en"])
def test_script_driven_presentation_survives_structured_render(key, language):
    from schemas.agent_workflow import StructuredSkillStoryboard
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    from services.storyboard.validation import prepare_skill_storyboard

    snap = SkillSnapshot.model_validate(snapshot_skills())
    value = _shot(1)
    value.visual_prose = 'A station ident appears with the requested logo, watermark and caption.'
    value.sound_design = 'A string score enters after the door closes.'
    value.effect_restrictions = ['No flashing lights']
    silent = value.model_copy(update={'sequence': 2, 'visual_prose': 'An empty doorway.',
                                      'sound_design': 'Full silence, including music and ambience.'})
    raw = StructuredSkillStoryboard.model_validate({'shots': [
        shot.model_dump(exclude={'prompt'}) for shot in (value, silent)
    ]})
    music, quiet = prepare_skill_storyboard(raw, snap, language, [], key).shots
    assert value.sound_design in music.prompt and value.visual_prose in music.prompt
    assert silent.sound_design in quiet.prompt and value.sound_design not in quiet.prompt
    for shot in (music, quiet):
        assert '无 BGM' not in shot.prompt and '无字幕' not in shot.prompt
        assert 'no subtitles' not in shot.prompt.lower()
        assert 'no background music' not in shot.prompt.lower()
