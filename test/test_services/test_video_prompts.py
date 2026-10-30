from prompts.video import (
    inject_last_frame_continuity_prompt,
    render_last_frame_continuity_instruction,
)


def test_尾帧首帧指令注入幂等且替换旧引用():
    first_mention = "@{参考图片:%2Fmedia%2Flast-frame-1.png}"
    second_mention = "@{参考图片:%2Fmedia%2Flast-frame-2.png}"
    original = "【镜头描述】\n人物从门外进入"

    first = inject_last_frame_continuity_prompt(original, first_mention)
    assert first.startswith(f'【首帧衔接】\n首帧参考：{first_mention}')
    assert inject_last_frame_continuity_prompt(first, first_mention) == first

    replaced = inject_last_frame_continuity_prompt(first, second_mention)
    assert second_mention in replaced
    assert first_mention not in replaced
    assert replaced.endswith(original)
    assert render_last_frame_continuity_instruction(second_mention) in replaced


def test_existing_bilingual_continuity_sections_can_be_replaced_without_templates():
    for heading in ("【首帧衔接】", "[First-frame continuity]"):
        original = heading + "\nOld reference.\n\nSaved prompt."
        result = inject_last_frame_continuity_prompt(original, "new-reference")
        assert result.endswith("Saved prompt.")
        assert "Old reference." not in result


def test_legacy_json_is_rendered_only_for_submission_and_uses_the_task_language():
    import json
    from prompts.video import normalize_last_frame_continuity_prompt
    mention = '@{参考图片:uploads%2Fframe.png}'
    saved = json.dumps({'first_frame_reference': mention}) + '\n\nOriginal dialogue and action.'
    for language, label in [('zh', '首帧参考：'), ('en', 'First-frame reference: ')]:
        result = normalize_last_frame_continuity_prompt(saved, language)
        assert label + mention in result
        assert 'first_frame_reference' not in result
        assert result.endswith('Original dialogue and action.')
        assert normalize_last_frame_continuity_prompt(result, language) == result
    assert saved.startswith('{"first_frame_reference":')
