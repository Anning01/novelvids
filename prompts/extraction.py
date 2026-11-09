"""Asset instruction rendering from the single skill pack."""

from prompts.skill_pack import render_skill


def render_cast_instructions(language: str) -> str:
    if language == 'en':
        return (
            'Read the entire chapter independently and inventory all visual assets in three separate arrays: '
            'characters (people, animals and groups), scenes (depicted locations), and items (visible props). '
            'Include each character with an action, spoken line or depicted presence. Classify presence as present, flashback '
            '(including enacted memories/dreams), or mentioned (background/name references only). '
            'Do not exclude a supporting character just because they appear once. Death does not exclude '
            'an enacted flashback. Include a short exact source quote for each classification. '
            'Merge aliases for the same identity; never merge different people sharing a title. '
            'Different asset categories may share a name or alias. Resolve catalog identities only within the same category. '
            'Reuse the exact registered name and ID when identifiable; use null ID for a new character. '
            'Preserve source-language names. Visible screens, holographic panels and interfaces belong in items, '
            'not characters; a bodiless voice or abstract concept has presence=voice_only and needs no visual asset. '
            'Classify by the source evidence, not the entity name: a system with an actual depicted body may be a character. '
            'List every depicted location and visible prop, even when no catalog entry exists. '
            'Do not invent personal names for unnamed speakers; use a distinct source-supported role. '
            'Return characters/scenes/items, with [] only for types absent from the chapter; no visual design prompts.'
        )
    return (
        '独立完整阅读本章，按三个数组清点全部视觉资产：characters 是角色、动物与群像，scenes 是实际演出的场景，items 是可视化道具。'
        '列出每个有动作、对白或被具体演出的角色、动物与群像。'
        'presence 区分 present（当前实际出场）、flashback（真正演出的回忆、梦境或闪回）、'
        'mentioned（仅在对白或背景中被提及）。不能因为配角只出现一次就遗漏；已去世者在回忆中演出仍算出场。'
        '每项必须提供能够判断身份和出场性质的短段准确原文 quote，不改写引文。'
        '同一人的别名合并，不能因师父、宗主等头衔相同而合并不同人。'
        '不同类型资产允许同名或共用别名，只能在同一类型内匹配目录身份，不能跨类型合并或替代。'
        '可匹配目录身份时使用准确标准名和 existing_asset_id；新角色 ID 为 null。姓名保持原文语言。'
        '屏幕、半透明面板、界面等可视载体归 items，不归 characters；没有可见形体的提示音、画外声音和抽象概念标为 voice_only，不强制生成人物外形。'
        '按原文证据分类，不按名称一刀切：有实际可见身体的拟人系统仍可归人物。'
        '本章实际演出的场景、可见道具即使未登记也必须逐项列出，不能只清点人物。'
        '未命名说话者使用原文可区分的身份称呼，不编造姓名。返回 characters/scenes/items，本章确实没有该类资产时才用空数组，不生成视觉设定。'
    )


def render_cast_scope(language: str, cast: dict, required_assets: tuple) -> str:
    import json
    rule = ('Complete every required asset in its listed category: 1=person, 2=scene, 3=item. '
            'Do not treat an item or a scene as a missing person. Include all new visible assets and flashback characters. '
            'Mention-only entries do not require a new asset unless already registered for placeholder completion.\n'
            if language == 'en' else
            '按必需名单给定的类型逐项完成：1=人物、2=场景、3=道具，不能把已输出的道具或场景当成缺失人物。'
            '包括新出场与回忆中演出的角色、本章实际场景和可见道具；仅被提及者不新建资产，'
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
