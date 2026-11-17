"""Prepare structured facts for asset extraction."""

from dataclasses import asdict

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


class ExtractionMessageBuilder:
    """Build project, registry and chapter facts without prompt instructions."""

    def build(self, context: ExtractionContext) -> dict:
        novel_payload = _drop_empty(asdict(context.novel))
        required_ids = {asset.id for asset in context.required_design_assets}
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
                    "variants": tuple(asdict(variant) for variant in asset.variants),
                    **({"requires_design_completion": True} if asset.id in required_ids else {}),
                }
            )
            for asset in context.assets
        ]
        chapter_payload = asdict(context.chapter)
        return {'project': novel_payload, 'known_assets': asset_payload, 'chapter': chapter_payload}
