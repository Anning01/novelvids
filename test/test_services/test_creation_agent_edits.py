import pytest
from pydantic import ValidationError

from schemas.creation_agent import ImagePromptEdit, StoryboardPromptEdit
from services.creation_agent.prompt_edits import prepare_storyboard_edit
from test.test_services.test_creation_agent_prompts import heroine, segmented_shot


def stored_prompt():
    from prompts.storyboard import format_storyboard_prompt

    shot = segmented_shot()
    return shot, format_storyboard_prompt(shot, entities=[heroine()])


def test_only_prompt_fields_are_writable():
    with pytest.raises(ValidationError):
        ImagePromptEdit(target_id=1, target_kind="asset", expected_version="v", prompt="风衣", main_image="new.png")
    for field in ("sequence", "duration", "asset_ids", "dialogue", "chapter_id"):
        with pytest.raises(ValidationError):
            StoryboardPromptEdit(scene_id=1, expected_version="v", changes={field: 9})


def test_structured_patch_preserves_existing_tracks_and_rebuilds_prompt():
    shot, prompt = stored_prompt()
    result = prepare_storyboard_edit(
        edit=StoryboardPromptEdit(scene_id=1, expected_version="v", changes={"lighting_and_atmosphere": "暖光从左侧照入"}),
        prompt=prompt, params=shot.model_dump(), sequence=shot.sequence,
        description=shot.description, duration=6, entities=[heroine()],
    )
    assert "暖光从左侧照入" in result["prompt"]
    assert result["prompt_params"]["segments"] == shot.model_dump()["segments"]
    assert result["prompt_params"]["dialogue"] == shot.dialogue
    assert "sequence" not in result and "duration" not in result


def test_stale_structured_parameters_cannot_replace_manual_text():
    shot, _ = stored_prompt()
    with pytest.raises(ValueError, match="手工|不一致"):
        prepare_storyboard_edit(
            edit=StoryboardPromptEdit(scene_id=1, expected_version="v", changes={"environment": "冷雨"}),
            prompt="用户刚刚写入的全新构图", params=shot.model_dump(), sequence=shot.sequence,
            description=shot.description, duration=6, entities=[heroine()],
        )


def test_legacy_text_edit_preserves_content_without_fabricating_parameters():
    result = prepare_storyboard_edit(
        edit=StoryboardPromptEdit(scene_id=1, expected_version="v", legacy_prompt="@{女主}在雨夜站台握伞，暖光从左侧照入。"),
        prompt="旧纯文本", params={}, sequence=6, description="站台", duration=6, entities=[heroine()],
    )
    assert "暖光从左侧照入" in result["prompt"]
    assert heroine().description in result["prompt"]
    assert result["prompt_params"] == {}


def test_repeated_legacy_edits_replace_generated_definitions_and_preserve_voice_sections():
    from prompts.creation_agent import render_prompt_definitions, without_prompt_definitions

    original = '@{女主}在窗边打开信封。'
    old_entity = heroine().model_copy(update={'description': '旧灰色风衣'})
    prior = render_prompt_definitions(original, [old_entity])
    prior += '\n\n【人物台词】\n“欢迎回家。”'
    assert without_prompt_definitions(prior) == original + '\n\n【人物台词】\n“欢迎回家。”'
    for _ in range(2):
        result = prepare_storyboard_edit(edit=StoryboardPromptEdit(scene_id=1, legacy_prompt=prior),
            prompt=prior, params={}, sequence=1, description='窗边', duration=3, entities=[heroine()])
        prior = result['prompt']
        assert prior.count('【当前请求资产定义】') == 1
        assert old_entity.description not in prior
        assert heroine().description in prior
        assert '“欢迎回家。”' in prior and '打开信封' in prior


def test_legacy_plain_names_and_retained_voice_references_receive_complete_definitions():
    from schemas.scene import SceneEntity
    entities = [heroine(), SceneEntity(name='值班室', aliases=[], description='木桌靠右，绿色档案柜靠左。', asset_type='场景'),
                SceneEntity(name='周鸣', aliases=[], description='三十岁，深蓝夹克。', asset_type='人物')]
    result = prepare_storyboard_edit(
        edit=StoryboardPromptEdit(scene_id=1, expected_version='v', legacy_prompt='女主推开值班室木门后停下，背景为柔和冷光。'),
        prompt='女主推开值班室木门后停下。', params={'dialogue': ['@{周鸣}：“和上一回一样。”']},
        sequence=3, description='推门', duration=6, entities=entities)
    assert '@{女主}推开@{值班室}木门后停下' in result['prompt']
    assert all(entity.description in result['prompt'] for entity in entities)
    assert result['prompt_params']['dialogue'] == ['@{周鸣}：“和上一回一样。”']


@pytest.mark.parametrize("text", ["镜头1的女生走向门口。", "服装同上，女主走向门口。", "@{陌生人物}走向门口。"])
def test_unresolved_dependencies_cannot_be_saved(text):
    with pytest.raises(ValueError):
        prepare_storyboard_edit(
            edit=StoryboardPromptEdit(scene_id=1, expected_version="v", legacy_prompt=text),
            prompt="旧文本", params={}, sequence=6, description="站台", duration=6, entities=[heroine()],
        )


def test_storyboard_edit_rejects_malformed_entity_reference():
    shot, prompt = stored_prompt()
    with pytest.raises(ValueError, match="素材引用格式"):
        prepare_storyboard_edit(
            edit=StoryboardPromptEdit(
                scene_id=1,
                expected_version="v",
                changes={
                    "segments": [{
                        "duration": 6,
                        "description": "握伞",
                        "shot_size_and_camera": "中景",
                        "visual_prose": "@{女主}站在站台中央",
                        "actions": ["@@女主@握紧雨伞"],
                        "camera_movement": "固定机位",
                    }],
                },
            ),
            prompt=prompt,
            params=shot.model_dump(),
            sequence=shot.sequence,
            description=shot.description,
            duration=6,
            entities=[heroine()],
        )


def test_valid_dialogue_is_not_rejected_by_a_previous_word_heuristic():
    shot, prompt = stored_prompt()
    shot.dialogue = ["女主说：和上一回一样。"]
    from prompts.storyboard import format_storyboard_prompt

    prompt = format_storyboard_prompt(shot, entities=[heroine()])
    result = prepare_storyboard_edit(
        edit=StoryboardPromptEdit(scene_id=1, expected_version="v", changes={"environment": "雨渐渐停下"}),
        prompt=prompt, params=shot.model_dump(), sequence=shot.sequence,
        description=shot.description, duration=6, entities=[heroine()],
    )
    assert "和上一回一样" in result["prompt"]


def test_prompt_modes_and_empty_patches_are_explicit():
    for body in ({}, {"changes": {}}, {"changes": {"environment": None}}, {"legacy_prompt": " "},
                 {"legacy_prompt": "新文本", "changes": {"environment": "雨"}}):
        with pytest.raises(ValidationError):
            StoryboardPromptEdit(scene_id=1, expected_version="v", **body)


def test_visual_patch_schema_does_not_offer_null_as_a_valid_edit():
    from schemas.creation_agent import StoryboardVisualChanges
    properties = StoryboardVisualChanges.model_json_schema()['properties']
    assert properties['transition']['type'] == 'string'
    assert properties['actions']['type'] == 'array'
    assert 'transition' not in StoryboardVisualChanges.model_json_schema().get('required', [])


def test_free_text_mode_keeps_existing_voice_tracks_and_other_metadata():
    result = prepare_storyboard_edit(
        edit=StoryboardPromptEdit(scene_id=1, expected_version="v", legacy_prompt="雨后的空站台，暖光从左侧照入。"),
        prompt="旧文本", params={"visual_prose": "过期画面", "narration": ["旁白：雨停了。"], "sound_design": "雨声"},
        sequence=1, description="站台", duration=6, entities=[],
    )
    assert result["prompt_params"] == {"narration": ["旁白：雨停了。"], "sound_design": "雨声"}
    assert "旁白：雨停了。" in result["prompt"] and "雨声" in result["prompt"]


def test_legacy_mode_also_rejects_continued_local_numbers():
    with pytest.raises(ValueError, match="从1开始"):
        prepare_storyboard_edit(
            edit=StoryboardPromptEdit(scene_id=1, expected_version="v", legacy_prompt="【镜头4 · 2s】\n空站台"),
            prompt="旧文本", params={}, sequence=6, description="站台", duration=6, entities=[],
        )
