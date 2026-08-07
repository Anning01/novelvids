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

GENDER_ALIASES = (
    ("女", (r"女性", r"\bfemale\b", r"\bwoman\b", r"\bgirl\b")),
    ("男", (r"男性", r"\bmale\b", r"\bman\b", r"\bboy\b")),
)
AGE_ALIASES = (
    ("中年", (r"中年", r"middle[- ]?aged", r"\bmidlife\b")),
    ("老年", (r"老年", r"高龄", r"年迈", r"\belderly\b", r"\bsenior\b", r"\baged\b")),
    ("少年", (r"少年", r"青少年", r"\badolescent\b", r"\bteen(?:ager)?\b")),
    ("儿童", (r"儿童", r"幼年", r"孩童", r"\bchild(?:hood)?\b", r"\bkid\b")),
    ("青年", (r"青年", r"年轻成人", r"young[- ]?adult", r"\badult\b")),
)
CHINESE_DECADE_AGE_GROUPS = (
    ("老年", ("六十", "七十", "八十", "九十", "百岁")),
    ("中年", ("四十", "五十")),
    ("青年", ("二十", "三十")),
)


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


def _trait_value(base_traits: str, label: str) -> str:
    match = re.search(
        rf"(?:^|\n)\s*(?:[-*]\s*)?\**{re.escape(label)}\**\s*[:：]\s*(.+?)(?=\r?\n|$)",
        base_traits or "",
        flags=re.IGNORECASE,
    )
    return match.group(1).strip(" *_`。.;；,，") if match else ""


def _normalize_gender(value: str) -> str | None:
    normalized = value.casefold()
    for result, patterns in GENDER_ALIASES:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return result
    return None


def _age_group_for_number(age: int) -> str | None:
    if age < 0 or age > 150:
        return None
    if age < 12:
        return "儿童"
    if age < 18:
        return "少年"
    if age < 40:
        return "青年"
    if age < 60:
        return "中年"
    return "老年"


def _normalize_age_group(value: str) -> str | None:
    normalized = value.casefold()
    numeric_age = re.search(
        r"(?<!\d)(\d{1,3})(?!\d)[-\s]*(?:岁|years?(?:[-\s]*old)?)",
        normalized,
    )
    if numeric_age:
        return _age_group_for_number(int(numeric_age.group(1)))
    for result, markers in CHINESE_DECADE_AGE_GROUPS:
        if any(marker in normalized for marker in markers):
            return result
    if (
        re.search(r"十[二三四五六七八九](?:岁|周岁)", normalized)
        or "十多岁" in normalized
    ):
        return "少年"
    for result, patterns in AGE_ALIASES:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return result
    return None


def _person_metadata(item: Person) -> dict[str, str]:
    metadata = {"reference_layout": item.reference_layout}
    if item.label == "群像":
        return metadata
    gender = (
        "其他（动物）"
        if item.label == "动物"
        else _normalize_gender(_trait_value(item.base_traits, "性别"))
    )
    age_group = _normalize_age_group(_trait_value(item.base_traits, "年龄"))
    if gender:
        metadata["gender"] = gender
    if age_group:
        metadata["age_group"] = age_group
    return metadata


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
                item_metadata = _person_metadata(item)

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
                metadata_updates: dict[str, str] = {}
                if asset_type == AssetTypeEnum.person:
                    metadata_updates = {
                        "reference_layout": item_metadata["reference_layout"]
                    }
                    if incoming_is_current:
                        metadata_updates = item_metadata
                existing.metadata = {**existing_metadata, **metadata_updates}
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
