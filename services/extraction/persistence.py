"""Transactional persistence for extracted project assets."""

import re

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from models.asset import Asset
from services.extraction.context import normalize_source_chapters
from services.extraction.extractor import (
    AssetExtractionResult,
    Item,
    Person,
    Scene,
)
from utils.enums import AssetTypeEnum


RESULT_ASSET_MAP = [
    (AssetTypeEnum.person, "persons"),
    (AssetTypeEnum.scene, "scenes"),
    (AssetTypeEnum.item, "items"),
]

ExtractedAsset = Person | Scene | Item


def _identity_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", (value or "").casefold())


def _identity_keys(asset: Asset) -> set[str]:
    return {
        key
        for key in (
            _identity_key(asset.canonical_name),
            *(_identity_key(alias) for alias in (asset.aliases or [])),
        )
        if key
    }


def _ordered_strings(*groups: list[str] | None) -> list[str]:
    result: list[str] = []
    for values in groups:
        for value in values or []:
            value = value.strip()
            if value and value not in result:
                result.append(value)
    return result


class AssetUpsertService:
    """Merge one extraction result atomically into the project asset registry."""

    async def save_result(
        self,
        *,
        novel_id: int,
        chapter_number: int,
        result: AssetExtractionResult,
    ) -> dict[str, list[dict[str, str]]]:
        summary: dict[str, list[dict[str, str]]] = {}
        async with in_transaction() as connection:
            for asset_type, result_key in RESULT_ASSET_MAP:
                summary[result_key] = await self._save_assets(
                    connection=connection,
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                    asset_type=asset_type,
                    items=getattr(result, result_key),
                )
        return summary

    async def _save_assets(
        self,
        *,
        connection: BaseDBAsyncClient,
        novel_id: int,
        chapter_number: int,
        asset_type: AssetTypeEnum,
        items: list[ExtractedAsset],
    ) -> list[dict[str, str]]:
        saved: list[dict[str, str]] = []
        existing_assets = await Asset.filter(
            novel_id=novel_id,
            asset_type=asset_type.value,
        ).using_db(connection)

        for item in items:
            item_metadata: dict[str, str] = {}
            if asset_type == AssetTypeEnum.person:
                item_metadata["reference_layout"] = getattr(
                    item,
                    "reference_layout",
                    "character_turnaround",
                )

            incoming_keys = {
                key
                for key in (
                    _identity_key(item.name),
                    *(_identity_key(alias) for alias in item.aliases),
                )
                if key
            }
            existing = next(
                (
                    asset
                    for asset in existing_assets
                    if incoming_keys & _identity_keys(asset)
                ),
                None,
            )

            if existing:
                existing_last_chapter = int(existing.last_updated_chapter or 0)
                existing_metadata = (
                    dict(existing.metadata)
                    if isinstance(existing.metadata, dict)
                    else {}
                )
                replaces_project_analysis = (
                    existing_metadata.get("analysis_source") == "project_analysis"
                    and bool(item.base_traits.strip())
                )
                incoming_is_current = (
                    replaces_project_analysis
                    or chapter_number >= existing_last_chapter
                )
                merged_aliases = _ordered_strings(
                    existing.aliases,
                    [item.name] if item.name != existing.canonical_name else [],
                    item.aliases,
                )
                existing_source_chapters = normalize_source_chapters(
                    existing.source_chapters
                )
                source_chapters = normalize_source_chapters(
                    (*existing_source_chapters, chapter_number)
                )

                existing.aliases = merged_aliases
                if incoming_is_current and item.description.strip():
                    existing.description = item.description
                if incoming_is_current and item.base_traits.strip():
                    existing.base_traits = item.base_traits
                if replaces_project_analysis:
                    existing_metadata.pop("analysis_source", None)
                existing.metadata = {**existing_metadata, **item_metadata}
                existing.source_chapters = list(source_chapters)
                existing.last_updated_chapter = (
                    chapter_number
                    if replaces_project_analysis
                    else max(existing_last_chapter, chapter_number)
                )
                await existing.save(
                    using_db=connection,
                    update_fields=[
                        "aliases",
                        "description",
                        "base_traits",
                        "metadata",
                        "source_chapters",
                        "last_updated_chapter",
                        "updated_at",
                    ],
                )
                saved.append({"name": item.name, "action": "updated"})
                continue

            created = await Asset.create(
                using_db=connection,
                novel_id=novel_id,
                asset_type=asset_type.value,
                canonical_name=item.name,
                aliases=item.aliases,
                description=item.description,
                base_traits=item.base_traits,
                metadata=item_metadata,
                source_chapters=[chapter_number],
                last_updated_chapter=chapter_number,
            )
            existing_assets.append(created)
            saved.append({"name": item.name, "action": "created"})

        return saved
