"""Prepare layered fact messages for asset extraction."""

import json
from dataclasses import asdict

from prompts.extraction import render_extraction_system
from prompts.catalog import text
from services.extraction.context import ExtractionContext


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


class ExtractionMessageBuilder:
    """Build rule, metadata, registry, and chapter messages in fixed order."""

    def build(
        self,
        context: ExtractionContext,
        prompt_language: str,
    ) -> list[dict[str, str]]:
        system_content = render_extraction_system(prompt_language)
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
                "content": text("extraction_fact", prompt_language, boundary="novel_metadata", payload=_compact_json(novel_payload)),
            },
            {"role": "user", "content": text("extraction_registry", prompt_language, payload=_compact_json(asset_payload))},
            {"role": "user", "content": text("extraction_chapter", prompt_language, payload=_compact_json(chapter_payload))},
        ]
