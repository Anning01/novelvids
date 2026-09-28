"""重制工坊视频拆解 Prompt 与严格 JSON 契约。

内容同步自 shengshimedia 无限画布复刻流水线；本模块保持无副作用，业务调用、
媒体加载、计费和持久化由 services/remake 负责。
"""

from typing import Any
from prompts.catalog import template, text
from prompts.schema import localized_schema


SINGLE_CHARACTER_PROMPT_PREFIX = template("remake_character_prefix.md", "zh")

SCENE_PROMPT_PREFIX = template("remake_scene_prefix.md", "zh")

ASSET_PROMPT = template("remake_assets.md", "zh")

PROMPT_TEMPLATE = template("remake_shots.md", "zh")

ASSET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string", "enum": ["人物", "动物", "群像"]},
                    "description": {"type": "string"},
                },
                "required": ["name", "label", "description"],
            },
        },
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
    },
    "required": ["characters", "scenes", "objects"],
}

DIALOGUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "speaker_asset_id": {"type": "string"},
        "speaker_name": {"type": "string"},
        "delivery": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["speaker_asset_id", "speaker_name", "delivery", "text"],
}

PROMPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "asset_refs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "asset_id": {"type": "string"},
                    "asset_name": {"type": "string"},
                    "asset_type": {
                        "type": "string",
                        "enum": ["character", "scene", "object"],
                    },
                },
                "required": ["asset_id", "asset_name", "asset_type"],
            },
        },
        "style": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "visual_style": {"type": "string"},
                "cinematography": {"type": "string"},
                "color_tone": {"type": "string"},
            },
            "required": ["visual_style", "cinematography", "color_tone"],
        },
        "global_conditions": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "time_weather": {"type": "string"},
                "environment_light": {"type": "string"},
                "spatial_relationships": {"type": "string"},
            },
            "required": ["time_weather", "environment_light", "spatial_relationships"],
        },
        "audio": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "has_bgm": {"type": "boolean"},
                "bgm_description": {"type": "string"},
            },
            "required": ["has_bgm", "bgm_description"],
        },
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "order": {"type": "integer"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "title": {"type": "string"},
                    "camera": {"type": "string"},
                    "description": {"type": "string"},
                    "environment_sound": {"type": "string"},
                    "dialogues": {"type": "array", "items": DIALOGUE_SCHEMA},
                },
                "required": [
                    "order",
                    "start_seconds",
                    "end_seconds",
                    "title",
                    "camera",
                    "description",
                    "environment_sound",
                    "dialogues",
                ],
            },
        },
        "transition": {"type": "string"},
        "effects": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "forbidden": {"type": "string"},
                "allowed": {"type": "string"},
            },
            "required": ["forbidden", "allowed"],
        },
        "confidence": {"type": "number"},
    },
    "required": [
        "asset_refs",
        "style",
        "global_conditions",
        "audio",
        "shots",
        "transition",
        "effects",
        "confidence",
    ],
}


def render_remake_request(
    prompt: str,
    *,
    context: str,
    index: int,
    schema: dict,
    include_segment_metadata: bool,
    language: str = "zh",
) -> str:
    import json

    parts = [prompt]
    if context:
        parts.append(context)
    if include_segment_metadata:
        parts.append(text("remake_index", language, index=index))
    parts.append(
        text(
            "remake_schema",
            language,
            schema=json.dumps(
                localized_schema(schema, language),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    )
    return "\n\n".join(parts)


def render_remake_prompt(kind: str, language: str) -> str:
    from prompts.language import output_language_rule

    return (
        template(
            {"assets": "remake_assets.md", "shots": "remake_shots.md"}[kind], language
        )
        + "\n"
        + output_language_rule(language)
    )


def render_remake_catalog(assets: list[dict], language: str) -> str:
    import json

    return text(
        "remake_catalog",
        language,
        catalog=json.dumps(assets, ensure_ascii=False, separators=(",", ":")),
    )
