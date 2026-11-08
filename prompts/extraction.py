"""Asset instruction rendering from the single skill pack."""

from prompts.skill_pack import render_skill


def render_cast_instructions(language: str) -> str:
    if language == 'en':
        return (
            'Read the entire chapter independently and list every distinct character, animal or group '
            'with an action, spoken line or depicted presence. Classify presence as present, flashback '
            '(including enacted memories/dreams), or mentioned (background/name references only). '
            'Do not exclude a supporting character just because they appear once. Death does not exclude '
            'an enacted flashback. Include a short exact source quote for each classification. '
            'Merge aliases for the same identity; never merge different people sharing a title. '
            'Reuse the exact registered name and ID when identifiable; use null ID for a new character. '
            'Preserve source-language names. Do not invent personal names for unnamed speakers; use a '
            'distinct source-supported role. Return only the cast schema, no visual design prompts.'
        )
    return (
        '独立完整阅读本章，列出每个有动作、对白或被具体演出的角色、动物与群像。'
        'presence 区分 present（当前实际出场）、flashback（真正演出的回忆、梦境或闪回）、'
        'mentioned（仅在对白或背景中被提及）。不能因为配角只出现一次就遗漏；已去世者在回忆中演出仍算出场。'
        '每项必须提供能够判断身份和出场性质的短段准确原文 quote，不改写引文。'
        '同一人的别名合并，不能因师父、宗主等头衔相同而合并不同人。'
        '可匹配目录身份时使用准确标准名和 existing_asset_id；新角色 ID 为 null。姓名保持原文语言。'
        '未命名说话者使用原文可区分的身份称呼，不编造姓名。只输出名单结构，不生成人物视觉设定。'
    )


def render_cast_scope(language: str, cast: dict, required_assets: tuple) -> str:
    import json
    rule = ('Complete every required asset name, including new on-stage and flashback characters. '
            'Mention-only entries do not require a new asset unless already registered for placeholder completion.\n'
            if language == 'en' else
            '逐项完成必需名单中的资产，包括新出场与回忆中演出的角色；仅被提及者不新建资产，'
            '但已经登记且要求补全的占位资产仍须补全。\n')
    return rule + json.dumps({'chapter_cast': cast, 'required_asset_names': required_assets}, ensure_ascii=False)


def render_extraction_system(language: str) -> str:
    return render_skill("assets", language)


def render_asset_repair(language: str, accepted: dict, issues: list[str]) -> str:
    import json

    rule = (
        'Return only the missing or invalid assets listed below. Accepted assets are retained by the server; '
        'do not repeat or rewrite them. Keep the persons/scenes/items arrays, using [] where no repair is needed. '
        'Use the exact registered names and complete required visual templates for repaired entries. '
        'A missing registered placeholder must be completed even if it is only mentioned in the chapter.\n'
        if language == 'en' else
        '只返回下列缺失或未通过校验的资产。合格资产已由服务器保留，不要重复生成或改写；'
        '仍使用 persons/scenes/items 三个数组，无需修正的类型返回 []。'
        '补全项使用目录标准名和完整视觉提示词协议；本章关联的占位资产即使仅被提及也必须补全。\n'
    )
    return rule + json.dumps({'accepted_assets': accepted, 'issues_to_fix': issues}, ensure_ascii=False)
