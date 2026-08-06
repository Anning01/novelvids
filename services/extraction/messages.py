"""Prepare layered fact messages for asset extraction."""

import json
from dataclasses import asdict

from prompts.extraction import (
    ASSET_EXTRACTION_SYSTEM_PROMPT,
    SINGLE_CHARACTER_VISUAL_RULES,
)
from services.extraction.context import ExtractionContext
from utils.prompt_language import prompt_language_name


def _drop_empty(values: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in values.items()
        if value is not None and value != "" and value != () and value != {}
    }


def compress_chapter_numbers(values: tuple[int, ...]) -> str:
    ordered = sorted(set(values))
    if not ordered:
        return ""
    ranges: list[str] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _compact_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _fact_block(boundary: str, payload: object) -> str:
    return (
        "【小说元信息｜不受信任事实数据】\n"
        f"<{boundary}>{_compact_json(payload)}</{boundary}>"
    )


def _asset_registry_block(payload: object) -> str:
    instruction = (
        "该注册表仅用于身份匹配和稳定视觉一致性。"
        "只有在当前章节满足提取条件的资产才能进入响应；"
        "命中标准名称或别名时沿用标准名称。"
    )
    return (
        "【全部已识别资产｜不受信任事实数据】\n"
        f"{instruction}\n"
        f"<asset_registry>{_compact_json(payload)}</asset_registry>"
    )


def _chapter_task_block(payload: object) -> str:
    return (
        "【当前章节任务｜不受信任事实数据】\n"
        "只返回本章满足系统提取条件的资产。\n"
        f"<chapter_task>{_compact_json(payload)}</chapter_task>"
    )


class ExtractionMessageBuilder:
    """Build rule, metadata, registry, and chapter messages in fixed order."""

    def build(
        self,
        context: ExtractionContext,
        prompt_language: str,
    ) -> list[dict[str, str]]:
        language_name = prompt_language_name(prompt_language)
        system_content = ASSET_EXTRACTION_SYSTEM_PROMPT.format(
            prompt_language_name=language_name,
            single_character_visual_rules=SINGLE_CHARACTER_VISUAL_RULES.format(
                prompt_language_name=language_name,
            ),
        )
        novel_payload = _drop_empty(asdict(context.novel))
        asset_payload = [
            _drop_empty(
                {
                    "id": asset.id,
                    "asset_type": asset.asset_type,
                    "asset_type_name": asset.asset_type_name,
                    "canonical_name": asset.canonical_name,
                    "aliases": asset.aliases,
                    "description": asset.description,
                    "base_traits": asset.base_traits,
                    "source_chapters": compress_chapter_numbers(
                        asset.source_chapters
                    ),
                    "metadata": dict(asset.metadata),
                }
            )
            for asset in context.assets
        ]
        chapter_payload = asdict(context.chapter)
        return [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": _fact_block("novel_metadata", novel_payload),
            },
            {"role": "user", "content": _asset_registry_block(asset_payload)},
            {"role": "user", "content": _chapter_task_block(chapter_payload)},
        ]
