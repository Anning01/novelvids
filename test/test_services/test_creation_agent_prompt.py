from prompts.creation_agent import render_creation_instructions, render_creation_request, render_creation_summary
from prompts.skill_pack import read_skill


def test_agent_request_does_not_duplicate_large_context():
    rendered = render_creation_request("调整光线")
    assert "调整光线" in rendered
    assert "reference_data" not in rendered and "expected_version" not in rendered


def test_agent_and_summary_preserve_permissions_and_evidence():
    rendered = render_creation_instructions(language="en")
    assert read_skill("base") in rendered and read_skill("editing") in rendered
    assert "language=en" in rendered
    assert "服务端权限" in rendered
    summary = render_creation_summary("之前摘要", [{"content": "本章都使用暖光"}])
    assert "previous_summary" in summary and "conversation_records" in summary


def test_truncated_chapter_instructions_require_scoped_reading():
    rules = read_skill("editing")
    assert "chapter_offset" in rules and "截断片段不能整段覆盖" in rules


def test_crud_and_selected_edit_use_the_same_skill():
    assert render_creation_instructions(language="zh", crud=True) == render_creation_instructions(language="zh")
    assert "计费" in read_skill("editing") and "回执" in read_skill("base")


def test_turn_limited_instructions_tell_the_model_tools_are_withdrawn():
    normal = render_creation_instructions(language="zh")
    limited = render_creation_instructions(language="zh", turn_limited=True)
    assert "工具已收起" not in normal
    assert limited.startswith(normal)
    assert "工具已收起" in limited and "直接" in limited and "最终回复" in limited
    assert "工具已收起" in render_creation_instructions(language="en", turn_limited=True)


def test_editing_skill_stops_sending_authorized_writes_through_a_declaration():
    rules = read_skill("editing")
    assert "仅“删除”需要在 get_creation_context 的 capabilities 里声明" in rules
    assert "复杂操作再通过 capabilities 启用" not in rules
