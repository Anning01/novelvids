"""Independent generation boundaries shared by the editor and creation agent."""

import re

import pytest
from pydantic import ValidationError

from prompts.storyboard import format_storyboard_prompt, referenced_entities
from schemas.scene import SceneEntity, ScenePromptSegment, SoraScenePromptConfig
from test.test_services.test_storyboard_prompts import _shot


def segmented_shot(sequence: int = 4) -> SoraScenePromptConfig:
    payload = _shot(sequence).model_dump()
    payload.update(
        duration="6s",
        visual_prose="夜色下的站台。",
        actions=["0s-6s: 女主从候车处走到站台门边。"],
        segments=[
            {
                "duration": 2,
                "description": action,
                "shot_size_and_camera": "中景",
                "visual_prose": f"@{{女主}}{action}",
                "actions": [f"@{{女主}}{action}"],
                "camera_movement": "固定机位",
            }
            for action in ("站在门边。", "握紧雨伞。", "转身看向站台。")
        ],
    )
    return SoraScenePromptConfig.model_validate(payload)


def heroine() -> SceneEntity:
    return SceneEntity(
        name="女主", aliases=[], asset_type="人物", asset_id=12,
        description="黑色齐肩短发，穿深灰色长风衣，左衣领破损，手持黑伞。",
    )


def test_independent_units_restart_local_numbers_and_include_complete_character():
    for sequence in (4, 5):
        shot = segmented_shot(sequence)
        prompt = format_storyboard_prompt(shot, entities=[heroine()])
        assert re.findall(r"【镜头(\d+) ·", prompt) == ["1", "2", "3"]
        assert heroine().description in prompt
        assert "0s-2s" in prompt and "2s-4s" in prompt and "4s-6s" in prompt
        assert "总时长：@{镜头时长:6s}" in prompt
        assert shot.sequence == sequence
        assert [item.asset_id for item in referenced_entities(shot, [heroine()])] == [12]


def test_local_number_is_not_an_agent_writable_field():
    segment = segmented_shot().segments[0].model_dump()
    with pytest.raises(ValidationError, match="Extra inputs"):
        ScenePromptSegment.model_validate({**segment, "sequence": 4})
    for field, value in (("description", "镜头4：女主走近"), ("visual_prose", "人物外貌同上"),
                         ("actions", ["镜头5里转身"])):
        with pytest.raises(ValidationError):
            ScenePromptSegment.model_validate({**segment, field: value})


@pytest.mark.parametrize("duration", [0, -1, float("inf"), float("nan")])
def test_invalid_segment_duration_is_rejected(duration):
    segment = segmented_shot().segments[0].model_dump()
    with pytest.raises(ValidationError):
        ScenePromptSegment.model_validate({**segment, "duration": duration})


def test_segments_cannot_silently_change_the_generation_duration():
    payload = segmented_shot().model_dump()
    payload["duration"] = "4s"
    with pytest.raises(ValidationError, match="总时长"):
        SoraScenePromptConfig.model_validate(payload)


def test_single_shot_rendering_stays_independent_of_database_sequence():
    prompt = format_storyboard_prompt(_shot(8))
    assert re.findall(r"【镜头(\d+) ·", prompt) == ["1"]
    assert "【核心生成指令｜高优先级】" in prompt


@pytest.mark.asyncio
async def test_storyboard_persistence_keeps_segments_and_their_references():
    from models.asset import Asset
    from models.chapter import Chapter
    from models.novel import Novel
    from schemas.scene import Storyboard
    from services.storyboard.handler import StoryboardTaskHandler
    from utils.enums import AssetTypeEnum

    novel = await Novel.create(name="内部镜头回归")
    chapter = await Chapter.create(novel=novel, number=1, name="第一章", content="雨夜")
    asset = await Asset.create(novel=novel, canonical_name="女主", asset_type=AssetTypeEnum.person.value)
    entity = heroine().model_copy(update={"asset_id": asset.id})
    scenes = await StoryboardTaskHandler()._save_scenes(
        chapter.id, Storyboard(shots=[segmented_shot()]), {}, 0.1, entities=[entity],
    )
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene.sequence == 4
    assert scene.duration == 6
    assert len(scene.prompt_params["segments"]) == 3
    assert await scene.assets.all().values_list("id", flat=True) == [asset.id]
    assert re.findall(r"【镜头(\d+) ·", scene.prompt) == ["1", "2", "3"]
