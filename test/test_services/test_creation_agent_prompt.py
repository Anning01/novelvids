from prompts.creation_agent import CREATION_AGENT_INSTRUCTIONS, CREATION_CRUD_INSTRUCTIONS, render_creation_request, render_creation_summary


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


def test_crud_prompt_uses_durable_receipts_and_keeps_creative_boundaries():
    assert 'recent_changes' in CREATION_CRUD_INSTRUCTIONS and 'changes_page' in CREATION_CRUD_INSTRUCTIONS
    assert '查询不到不代表永久删除' in CREATION_CRUD_INSTRUCTIONS
    assert '只有 apply_creation_changes 写入业务内容' in CREATION_CRUD_INSTRUCTIONS
    assert '从1开始' in CREATION_CRUD_INSTRUCTIONS
    assert '不写“镜头1的女生”' in CREATION_CRUD_INSTRUCTIONS
    assert '类别用人物、场景、道具等中文' in CREATION_CRUD_INSTRUCTIONS
    assert '不操作书稿、项目和模型配置、计费、媒体生成' in CREATION_CRUD_INSTRUCTIONS
