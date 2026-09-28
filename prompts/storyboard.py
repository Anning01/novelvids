"""Prompt templates and pure renderers for storyboard generation."""

from prompts.catalog import template, text

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from prompts.storyboard_strategies import (
    CINEMATIC_STORYBOARD_STRATEGY,
    StoryboardStrategyPrompt,
)
from utils.prompt_language import normalize_prompt_language
from prompts.language import output_language_rule
from prompts.labels import prompt_label


class StoryboardEntity(Protocol):
    """Minimum entity data required by the storyboard prompt renderer."""

    name: str
    aliases: list[str]
    description: str
    asset_type: str


class StoryboardShot(Protocol):
    """Minimum shot data required by the persisted prompt renderer."""

    duration: object
    sequence: int
    description: str
    shot_size_and_camera: str
    visual_style: str
    effect_restrictions: list[str]
    time_setting: str
    environment: str
    spatial_relationships: str
    visual_prose: str
    actions: list[str]
    format_and_look: str
    lenses_and_filtration: str
    lighting_and_atmosphere: str
    grade_and_palette: str
    camera_movement: str
    sound_design: str
    narration: list[str]
    dialogue: list[str]
    transition: str
    allowed_effects: list[str]


class StoryboardSegment(Protocol):
    duration: float
    description: str
    shot_size_and_camera: str
    visual_prose: str
    actions: list[str]
    camera_movement: str


STORYBOARD_LANGUAGE_INSTRUCTIONS = {
    lang: text("storyboard_language", lang) for lang in ("zh", "en")
}


STORYBOARD_SYSTEM_PROMPT = template("storyboard_system.md", "zh")


STORYBOARD_ASSET_MESSAGE = template("storyboard_assets.md", "zh")


STORYBOARD_NARRATIVE_MESSAGE = template("storyboard_narrative.md", "zh")

STORYBOARD_CONSTRAINT_MESSAGE = template("storyboard_constraints.md", "zh")


STORYBOARD_INITIAL_TASK_MESSAGE = template("storyboard_initial.md", "zh")


STORYBOARD_CONTINUATION_TASK_MESSAGE = template("storyboard_continue.md", "zh")


_REFERENCE_TEXT_FIELDS = (
    "description",
    "shot_size_and_camera",
    "visual_style",
    "time_setting",
    "visual_prose",
    "environment",
    "spatial_relationships",
    "format_and_look",
    "lenses_and_filtration",
    "lighting_and_atmosphere",
    "grade_and_palette",
    "camera_movement",
    "sound_design",
    "transition",
)
_REFERENCE_LIST_FIELDS = (
    "effect_restrictions",
    "actions",
    "narration",
    "dialogue",
    "allowed_effects",
)
_BRACED_REFERENCE_PATTERN = re.compile(r"@\{([^}]+)\}")
_LEGACY_REFERENCE_PATTERN = re.compile(r"@[\w\u4e00-\u9fff·]+")
_UNSAFE_AUTOMATIC_ALIASES = {
    "二人",
    "众人",
    "少年",
    "少女",
    "老人",
    "老者",
    "男人",
    "女人",
    "男子",
    "女子",
    "对方",
    "那人",
}


def _safe_canonical_asset_name(value: object) -> str:
    name = str(value or "").strip()
    if not name or any(character in name for character in "@{}\n\r"):
        return ""
    return name


def _safe_automatic_alias(value: object) -> str:
    name = _safe_canonical_asset_name(value)
    if len(name) < 2 or name in _UNSAFE_AUTOMATIC_ALIASES:
        return ""
    return name


def _asset_reference_candidates(
    entities: Sequence[StoryboardEntity],
) -> list[tuple[str, str]]:
    """返回可自动补标的全部资产名称，并排除有歧义的别名。"""
    canonical_names = {
        name for entity in entities if (name := _safe_canonical_asset_name(entity.name))
    }
    candidates = {name: name for name in canonical_names}
    alias_owners: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        canonical_name = _safe_canonical_asset_name(entity.name)
        if not canonical_name:
            continue
        for raw_alias in entity.aliases:
            alias = _safe_automatic_alias(raw_alias)
            if alias and alias not in canonical_names:
                alias_owners[alias].add(canonical_name)
    for alias, owners in alias_owners.items():
        if len(owners) == 1:
            candidates[alias] = next(iter(owners))
    return sorted(candidates.items(), key=lambda item: (-len(item[0]), item[0]))


def _normalize_asset_reference_text(
    text: str,
    candidates: Sequence[tuple[str, str]],
) -> str:
    if not text or not candidates:
        return text

    protected: list[str] = []

    def protect(value: str) -> str:
        placeholder = f"\ue000{len(protected)}\ue001"
        protected.append(value)
        return placeholder

    candidate_map = dict(candidates)

    def protect_braced(match: re.Match[str]) -> str:
        raw_name = match.group(1).strip()
        canonical_name = candidate_map.get(raw_name)
        return protect(f"@{{{canonical_name}}}" if canonical_name else match.group(0))

    normalized = _BRACED_REFERENCE_PATTERN.sub(protect_braced, text)

    # 兼容旧格式 @资产名，并统一升级为带花括号的正式名。模型常会把后续
    # 中文动作直接连在名称后面（例如 ``@羽宁沿着步道走``），因此必须按
    # 已登记资产名最长优先精确消费，不能依赖单词边界。
    for name, canonical_name in candidates:
        pattern = re.compile(rf"@{re.escape(name)}")
        normalized = pattern.sub(
            lambda _match, canonical=canonical_name: protect(f"@{{{canonical}}}"),
            normalized,
        )

    # 未识别的旧格式引用保持原样，避免在其内部再次替换普通资产名。
    normalized = _LEGACY_REFERENCE_PATTERN.sub(
        lambda match: protect(match.group(0)),
        normalized,
    )
    for name, canonical_name in candidates:
        if name in normalized:
            normalized = normalized.replace(name, protect(f"@{{{canonical_name}}}"))
    for index, value in enumerate(protected):
        normalized = normalized.replace(f"\ue000{index}\ue001", value)
    return normalized


def normalize_storyboard_reference_text(
    text: str, entities: Sequence[StoryboardEntity]
) -> str:
    """Use the shared name/alias rules for free-text and structured prompts alike."""
    return _normalize_asset_reference_text(text, _asset_reference_candidates(entities))


def normalized_storyboard_reference_fields(
    shot: StoryboardShot,
    entities: Sequence[StoryboardEntity],
) -> dict[str, object]:
    """为模型漏写的普通资产名补齐正式引用语法，返回非破坏性字段更新。"""
    candidates = _asset_reference_candidates(entities)
    if not candidates:
        return {}

    updates: dict[str, object] = {}
    for field_name in _REFERENCE_TEXT_FIELDS:
        original = str(getattr(shot, field_name))
        normalized = _normalize_asset_reference_text(original, candidates)
        if normalized != original:
            updates[field_name] = normalized
    for field_name in _REFERENCE_LIST_FIELDS:
        original = list(getattr(shot, field_name))
        normalized = [
            _normalize_asset_reference_text(str(value), candidates)
            for value in original
        ]
        if normalized != original:
            updates[field_name] = normalized
    return updates


def _asset_payload(entities: Sequence[StoryboardEntity]) -> str:
    payload = [
        {
            "asset_type": entity.asset_type,
            "canonical_name": entity.name,
            "aliases": entity.aliases,
            "visual_description": entity.description,
            "reference_syntax": f"@{{{entity.name}}}",
        }
        for entity in entities
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _continuation_payload(previous_shot: StoryboardShot) -> str:
    payload = {
        "sequence": previous_shot.sequence,
        "title": previous_shot.description,
        "duration": str(previous_shot.duration),
        "time_setting": previous_shot.time_setting,
        "environment": previous_shot.environment,
        "spatial_relationships": previous_shot.spatial_relationships,
        "last_actions": previous_shot.actions[-2:],
        "transition": previous_shot.transition,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_storyboard_messages(
    long_text: str,
    entities: Sequence[StoryboardEntity],
    prompt_language: str = "zh",
    *,
    batch_index: int = 0,
    batch_count: int = 1,
    next_sequence: int = 1,
    previous_shot: StoryboardShot | None = None,
    strategy: StoryboardStrategyPrompt = CINEMATIC_STORYBOARD_STRATEGY,
    creative_constraints: Sequence[dict] = (),
) -> list[dict[str, str]]:
    """Build stable rules and request facts as separate chat messages."""
    language = normalize_prompt_language(prompt_language)
    from prompts.storyboard_strategies import localized_strategy

    strategy = localized_strategy(strategy, language)
    task_template = (
        template("storyboard_continue.md", language)
        if previous_shot is not None
        else template("storyboard_initial.md", language)
    )
    task_content = task_template.format(
        batch_number=batch_index + 1,
        batch_count=batch_count,
        next_sequence=next_sequence,
        previous_shot=(
            _continuation_payload(previous_shot) if previous_shot is not None else ""
        ),
    )
    return [
        {
            "role": "system",
            "content": template("storyboard_system.md", language).format(
                language_instruction=STORYBOARD_LANGUAGE_INSTRUCTIONS[language]
                + "\n"
                + output_language_rule(language),
            )
            + (f"\n\n{strategy.generation_rules}" if strategy.generation_rules else ""),
        },
        {
            "role": "user",
            "content": template("storyboard_assets.md", language).format(
                asset_registry=_asset_payload(entities),
            ),
        },
        {
            "role": "user",
            "content": template("storyboard_narrative.md", language).format(
                long_text=long_text
            ),
        },
        {"role": "user", "content": task_content},
        *(
            [
                {
                    "role": "user",
                    "content": template("storyboard_constraints.md", language).format(
                        constraints=json.dumps(
                            list(creative_constraints), ensure_ascii=False
                        )
                    ),
                }
            ]
            if creative_constraints
            else []
        ),
    ]


def _duration_token(value: object) -> str:
    """Normalize storyboard duration to the token understood by the prompt editor."""
    raw = str(value or "").strip().lower().removesuffix("s")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = 6
    normalized = str(int(seconds)) if seconds.is_integer() else str(round(seconds, 1))
    return f"@{{镜头时长:{normalized}s}}"


def _join_values(values: Sequence[str], fallback: str = "无") -> str:
    normalized = [str(value).strip() for value in values if str(value).strip()]
    return "、".join(normalized) if normalized else fallback


def _shot_search_text(shot: StoryboardShot) -> str:
    values: list[object] = [
        *(getattr(shot, field_name) for field_name in _REFERENCE_TEXT_FIELDS),
        *(
            value
            for field_name in _REFERENCE_LIST_FIELDS
            for value in getattr(shot, field_name)
        ),
    ]
    for segment in getattr(shot, "segments", ()):
        values.extend((segment.description, segment.visual_prose, *segment.actions))
    return "\n".join(str(value) for value in values)


def entity_reference_names(
    text: str,
    entities: Sequence[StoryboardEntity],
) -> list[StoryboardEntity]:
    """返回在文本中以 `@{实体名}` / `@实体名` 形式被引用的实体。

    实体名或别名只要命中一次即视为被引用，这是分镜资产引用的唯一判定逻辑。
    """
    return [
        entity
        for entity in entities
        if any(
            f"@{{{name}}}" in text or f"@{name}" in text
            for name in (entity.name, *entity.aliases)
        )
    ]


def referenced_entities(
    shot: StoryboardShot,
    entities: Sequence[StoryboardEntity],
) -> list[StoryboardEntity]:
    """返回镜头实际引用的实体。"""
    return entity_reference_names(_shot_search_text(shot), entities)


ASSET_REFERENCE_LABELS = (
    ("人物", "角色参考", "角色设定图"),
    ("物品", "道具参考", "道具概念设计图"),
    ("场景", "场景参考", "场景概念图"),
)


def without_inline_reference_descriptions(
    prompt: str, reference_only_types: Sequence[str]
) -> str:
    """Remove only renderer-owned detail entries; keep references and narrative prose."""
    if not reference_only_types:
        return prompt
    boundaries = "|".join(
        re.escape(label)
        for _, summary, detail in ASSET_REFERENCE_LABELS
        for label in (
            summary,
            detail,
            prompt_label(summary, "en"),
            prompt_label(detail, "en"),
        )
    )

    def clean_section(match: re.Match) -> str:
        body = match.group(2)
        for kind, _, detail in ASSET_REFERENCE_LABELS:
            if kind in reference_only_types:
                for label in (detail, prompt_label(detail, "en")):
                    body = re.sub(
                        r"(?ms)^[ \t]*"
                        + re.escape(label)
                        + r"[：:].*?(?=^[ \t]*(?:"
                        + boundaries
                        + r")[：:]|\Z)",
                        "",
                        body,
                    )
        return match.group(1) + body

    return re.sub(
        r"(?ms)(^(?:【角色 / 道具 / 场景引用】|\[Character / Prop / Location references\])[^\S\n]*\n)(.*?)(?=^(?:【|\[)|\Z)",
        clean_section,
        prompt,
    )


def _format_asset_references(
    shot: StoryboardShot, entities: Sequence[StoryboardEntity], language: str = "zh"
) -> str:
    normalized_search_text = _normalize_asset_reference_text(
        _shot_search_text(shot), _asset_reference_candidates(entities)
    )
    referenced = entity_reference_names(normalized_search_text, entities)
    if not referenced:
        return prompt_label("本镜头未引用已登记资产。", language)
    sections: list[str] = []
    for asset_type, summary_label, detail_label in ASSET_REFERENCE_LABELS:
        category_entities = [
            entity for entity in referenced if entity.asset_type == asset_type
        ]
        if not category_entities:
            continue
        sections.append(
            f"{prompt_label(summary_label, language)}：{_join_values([f'@{{{entity.name}}}' for entity in category_entities])}"
        )
        if asset_type not in getattr(shot, "reference_only_types", ()):
            sections.extend(
                (
                    f"{prompt_label(detail_label, language)}：@{{{entity.name}}}。{entity.description}"
                    for entity in category_entities
                )
            )
    return "\n".join(sections)


_TIMELINE_START_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*[-–—]")


def _timeline_start(value: str) -> float:
    match = _TIMELINE_START_RE.match(value)
    return float(match.group(1)) if match else float("inf")


def _format_primary_generation_instruction(
    shot: StoryboardShot, language: str = "zh"
) -> str:
    """把模型最容易漏掉的动作与人声前置到镜头主指令。"""
    actions = "；".join(shot.actions) or prompt_label("保持当前可见状态", language)
    voice_tracks = sorted([*shot.narration, *shot.dialogue], key=_timeline_start)
    voices = "；".join(voice_tracks) or prompt_label(
        "无人物台词、旁白或人物内心 OS", language
    )
    return "\n".join(
        (
            prompt_label("【核心生成指令｜高优先级】", language),
            f"{prompt_label('初始画面：', language)}{shot.visual_prose}",
            f"{prompt_label('动作时间轴：', language)}{actions}",
            f"{prompt_label('人声时间轴：', language)}{voices}",
            f"{prompt_label('同步声音：', language)}{shot.sound_design}",
        )
    )


def _format_prompt_segments(
    segments: Sequence[StoryboardSegment], language: str = "zh"
) -> list[str]:
    """Render locally numbered segments; never inherit the chapter sequence."""
    parts: list[str] = []
    elapsed = 0.0
    for index, segment in enumerate(segments, start=1):
        end = elapsed + segment.duration
        parts.extend(
            (
                f"{prompt_label('【镜头', language)}{index} · {_duration_token(segment.duration)} · {segment.shot_size_and_camera} · {segment.description}{prompt_label('】', language)}",
                f"{prompt_label('时间范围：', language)}{elapsed:g}s-{end:g}s",
                f"{prompt_label('初始画面：', language)}{segment.visual_prose}",
                f"{prompt_label('运镜：', language)}{segment.camera_movement}",
                *segment.actions,
            )
        )
        elapsed = end
    return parts


def format_storyboard_prompt(
    shot: StoryboardShot,
    prompt_language: str = "zh",
    *,
    entities: Sequence[StoryboardEntity] = (),
    strategy: StoryboardStrategyPrompt = CINEMATIC_STORYBOARD_STRATEGY,
) -> str:
    """Render one structured shot as the stable professional video prompt."""
    language = normalize_prompt_language(prompt_language)
    from prompts.storyboard_strategies import localized_strategy

    strategy = localized_strategy(strategy, language)
    duration_token = _duration_token(shot.duration)
    dialogue = "\n".join(shot.dialogue)
    shot_body_parts = [shot.visual_prose, *shot.actions]
    narration = "\n".join(shot.narration)
    if narration:
        shot_body_parts.extend(
            (prompt_label("【旁白 / 内心 OS】", language), narration)
        )
    if dialogue:
        if narration:
            shot_body_parts.append(prompt_label("【人物台词】", language))
        shot_body_parts.append(dialogue)
    shot_body_parts.append(f"{prompt_label('环境音：', language)}{shot.sound_design}")
    segments = getattr(shot, "segments", ())
    if segments:
        details = [
            _format_primary_generation_instruction(shot, language),
            *_format_prompt_segments(segments, language),
            *(
                [prompt_label("【旁白 / 内心 OS】", language), narration]
                if narration
                else []
            ),
            *([prompt_label("【人物台词】", language), dialogue] if dialogue else []),
            f"{prompt_label('环境音：', language)}{shot.sound_design}",
        ]
    else:
        details = [
            f"{prompt_label('【镜头1 · ', language)}{duration_token} · {shot.shot_size_and_camera} · {shot.description}{prompt_label('】', language)}",
            _format_primary_generation_instruction(shot, language),
            prompt_label("【详细执行】", language),
            *shot_body_parts,
        ]
    prompt = "\n".join(
        (
            prompt_label("【禁止项】", language),
            prompt_label(strategy.prohibitions, language),
            "",
            prompt_label("【风格定调】", language),
            f"{prompt_label('视觉风格：', language)}{shot.visual_style}",
            f"{prompt_label('摄影规格：', language)}{shot.format_and_look}；{shot.lenses_and_filtration}；{shot.camera_movement}",
            f"{prompt_label('色彩基调：', language)}{shot.lighting_and_atmosphere}；{shot.grade_and_palette}",
            f"{prompt_label('特效禁令：', language)}{_join_values(shot.effect_restrictions)}",
            "",
            prompt_label("【角色 / 道具 / 场景引用】", language),
            _format_asset_references(shot, entities, language),
            "",
            prompt_label("【全局前置条件】", language),
            f"{prompt_label('时间：', language)}{shot.time_setting}",
            f"{prompt_label('环境：', language)}{shot.environment}",
            f"{prompt_label('空间关系：', language)}{shot.spatial_relationships}",
            "",
            prompt_label("【镜头描述】", language),
            *details,
            "",
            prompt_label("【转场方式】", language),
            shot.transition,
            "",
            prompt_label("【特效规范】", language),
            f"{prompt_label('禁止：', language)}{_join_values(shot.effect_restrictions)}",
            f"{prompt_label('允许：', language)}{_join_values(shot.allowed_effects, prompt_label('无特殊效果，纯自然光写实拍摄', language))}",
            "",
            f"{prompt_label('总时长：', language)}{duration_token}",
        )
    )
    return _normalize_asset_reference_text(
        prompt, _asset_reference_candidates(entities)
    )
