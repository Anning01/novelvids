"""Pure instructions for step handoffs and bounded creative corrections."""


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
    if language == 'en':
        return 'Select sources using only chapter_id and the supplied reference_id. The server resolves original text and offsets; do not copy long quotations.'
    return '方案选段只填写 chapter_id 和候选给出的 reference_id。原文与位置由服务器解析，不抄写长引文。'
