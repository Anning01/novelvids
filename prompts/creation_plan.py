"""Pure instructions for step handoffs and bounded creative corrections."""


def asset_request_instructions(language: str) -> str:
    if language == 'en':
        return ('Set asset_scope=targeted when the user reports specific missing characters, locations or props, '
                'including contextual questions such as "Where is the protagonist’s sword?" about missing assets. '
                'Record the exact request in requirements. Use chapter for a complete inventory. '
                'Use asset_mode=fill_missing for omissions; revise only for explicitly requested changes. '
                'A general informational question does not authorize production.')
    return ('用户指出具体角色、场景或道具遗漏（包括在补漏语境中说“主角的剑呢”）时，asset_scope=targeted，'
            '在 requirements 保留原话及指定对象，只核对补全这些对象；整章清点才用 chapter。'
            '遗漏补全用 asset_mode=fill_missing，明确修改已有设计才用 revise。普通知识问答不授权生产。')


def step_requirements(language: str) -> str:
    if language == 'en':
        return ('Apply only the current step_context requirements and instructions. The original message is '
                'source attribution, not permission to apply another chapter’s requirements. Preserve the '
                'mandatory output contract. Use the exact supplied excerpts and assets; do not invent sources.')
    return ('仅落实 step_context 中当前步骤适用的要求与编排方案。原始消息用于来源核对，'
            '不能将其他章节的要求套用到当前步骤。保留必需输出协议；使用提供的准确原文与资产，不编造来源。')


def correction_instructions(language: str) -> str:
    if language == 'en':
        return 'Revise the candidate using creative_check findings. Preserve correct content and the mandatory output format.'
    return '根据 creative_check 的具体问题修正候选，保留已正确的内容与必需输出格式。'


def reading_reference_instructions(language: str) -> str:
    if language == 'en':
        return ('The paragraphs are the complete source page with server-owned IDs. Select each candidate using '
                'chapter_id, first_paragraph and last_paragraph only. Do not calculate start/end or copy quote. '
                'The server retrieves the exact original text. This reference protocol supersedes legacy quote-copying instructions.')
    return ('paragraphs 是当前页完整原文，段落编号由服务器提供。每个候选只填写 chapter_id、first_paragraph、last_paragraph；'
            '不要计算 start/end，不要填写 quote，原文由服务器取回。此引用协议优先于历史技能中要求抄写长引文的说明。')


def plan_reference_instructions(language: str) -> str:
    reuse = ('reused_asset_chapter_ids are verified, saved asset results. Keep their asset steps in fill_missing mode with no source excerpts; '
             'empty pages for those chapters means reuse, not a new reading. Asset step modes must match brief.asset_mode.\n'
             if language == 'en' else
             'reused_asset_chapter_ids 对应已经核对的完整资产结果，其资产步骤保持 fill_missing 且 sources=[]；'
             '这些章节的 pages 为空表示直接复用，不是新阅读结果。资产步骤的 mode 必须与 brief.asset_mode 一致。\n')
    if language == 'en':
        return reuse + 'Select sources using only chapter_id and the supplied reference_id. The server resolves original text and offsets; do not copy long quotations.'
    return reuse + '方案选段只填写 chapter_id 和候选给出的 reference_id。原文与位置由服务器解析，不抄写长引文。'


def chapter_sections_instructions(sections: list[tuple[str, str]], language: str) -> str:
    heading = ('Generate ONE complete chapter storyboard covering ALL narrative sections below in order. '
        'Each section is part of this chapter, not a separate production request. Local wording such as "this step" '
        'limits only that section, not the complete chapter. Maintain continuity between sections.' if language == 'en' else
        '以下是同一章按叙事顺序排列的段落。一次生成完整章节分镜，必须覆盖全部段落并保持衔接，不是分别生成多个任务。'
        '每段中的“本步骤”“仅覆盖”等表述只限定该段，不限制整章内容。')
    return heading + '\n\n' + '\n\n'.join(f'{index}. {label}\n{instruction}' for index, (label, instruction) in enumerate(sections, 1))


def resolved_storyboard_resources_instructions(language: str) -> str:
    if language == 'en':
        return 'The selected visual style and narrative rules are already supplied in project.video_style and project.storyboard_rules. Apply them directly; no skill lookup is needed.'
    return '当前选定的画面风格和叙事规则已提供在 project.video_style、project.storyboard_rules，直接遵守这些规则，无需再次读取技能库。'
