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
