from prompts.creation_agent import CREATION_AGENT_INSTRUCTIONS, render_creation_request, render_creation_summary


def test_agent_request_does_not_duplicate_large_context():
    rendered = render_creation_request('调整光线')
    assert '调整光线' in rendered
    assert 'reference_data' not in rendered
    assert 'expected_version' not in rendered


def test_agent_and_summary_prompts_define_permissions_and_memory_boundaries():
    assert '只有 update_image_prompt 和 update_storyboard_prompt' in CREATION_AGENT_INSTRUCTIONS
    assert '不能写“镜头1的女生”' in CREATION_AGENT_INSTRUCTIONS
    assert '局部一次修改' in CREATION_AGENT_INSTRUCTIONS
    assert '最终回复只用简体中文和用户可见的对象名称' in CREATION_AGENT_INSTRUCTIONS
    assert '不展示数据库ID' in CREATION_AGENT_INSTRUCTIONS
    assert 'edit_mode 为 legacy_prompt' in CREATION_AGENT_INSTRUCTIONS
    assert '当前 prompt 是权威画面' in CREATION_AGENT_INSTRUCTIONS
    assert '都不构成范围歧义' in CREATION_AGENT_INSTRUCTIONS
    assert '不能承诺修改、解锁或同步项目锁定身份' in CREATION_AGENT_INSTRUCTIONS
    assert '不发送null' in CREATION_AGENT_INSTRUCTIONS
    summary = render_creation_summary('之前摘要', [{'content': '本章都使用暖光'}])
    assert 'previous_summary' in summary and 'conversation_records' in summary


def test_truncated_chapter_instructions_require_scoped_reading_instead_of_inventing_plot():
    assert 'content_truncated' in CREATION_AGENT_INSTRUCTIONS
    assert 'chapter_offset' in CREATION_AGENT_INSTRUCTIONS
    assert '不要假装已读完整章节' in CREATION_AGENT_INSTRUCTIONS
    assert '仅按任务需要读取当前章' in CREATION_AGENT_INSTRUCTIONS
