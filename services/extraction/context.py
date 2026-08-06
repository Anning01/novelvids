"""Immutable database snapshots used to prepare asset extraction requests."""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from utils.enums import AssetTypeEnum


EXTRACTABLE_ASSET_TYPE_VALUES = tuple(
    asset_type.value
    for asset_type in (
        AssetTypeEnum.person,
        AssetTypeEnum.scene,
        AssetTypeEnum.item,
    )
)


def normalize_source_chapters(
    values: object,
) -> tuple[int, ...]:
    if values is None or isinstance(values, Mapping):
        candidates: Iterable[object] = ()
    elif isinstance(values, (str, bytes, bytearray)):
        candidates = (values,)
    elif isinstance(values, Iterable):
        candidates = values
    else:
        candidates = (values,)

    normalized: set[int] = set()
    for value in candidates:
        if isinstance(value, bool):
            continue
        if isinstance(value, float) and (
            not math.isfinite(value) or not value.is_integer()
        ):
            continue
        try:
            normalized.add(int(value))
        except (TypeError, ValueError, OverflowError):
            continue
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class NovelExtractionMetadata:
    name: str
    author: str | None
    description: str | None
    tags: tuple[str, ...]
    story_outline: str | None
    project_type: str | None
    project_setting: str | None


@dataclass(frozen=True)
class KnownAssetSnapshot:
    id: int
    asset_type: int
    asset_type_name: str
    canonical_name: str
    aliases: tuple[str, ...]
    description: str | None
    base_traits: str | None
    source_chapters: tuple[int, ...]
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class ChapterExtractionInput:
    id: int
    number: int
    name: str
    content: str


@dataclass(frozen=True)
class ExtractionContext:
    novel: NovelExtractionMetadata
    assets: tuple[KnownAssetSnapshot, ...]
    chapter: ChapterExtractionInput


class ExtractionContextLoader:
    """Load a chapter and its project-wide, extraction-safe context."""

    async def load(self, *, novel_id: int, chapter_id: int) -> ExtractionContext:
        chapter = await Chapter.get(id=chapter_id)
        if chapter.novel_id != novel_id:
            raise ValueError(f"章节 {chapter_id} 不属于小说 {novel_id}")

        novel = await Novel.get(id=novel_id)
        assets = await Asset.filter(
            novel_id=novel_id,
            asset_type__in=EXTRACTABLE_ASSET_TYPE_VALUES,
        ).order_by("asset_type", "id")

        return ExtractionContext(
            novel=NovelExtractionMetadata(
                name=novel.name,
                author=novel.author,
                description=novel.description,
                tags=tuple(novel.tags or ()),
                story_outline=novel.story_outline,
                project_type=novel.project_type,
                project_setting=novel.project_setting,
            ),
            assets=tuple(self._asset_snapshot(asset) for asset in assets),
            chapter=ChapterExtractionInput(
                id=chapter.id,
                number=chapter.number,
                name=chapter.name,
                content=chapter.content or "",
            ),
        )

    @staticmethod
    def _asset_snapshot(asset: Asset) -> KnownAssetSnapshot:
        metadata = asset.metadata if isinstance(asset.metadata, Mapping) else {}
        return KnownAssetSnapshot(
            id=asset.id,
            asset_type=asset.asset_type,
            asset_type_name=AssetTypeEnum(asset.asset_type).nickname,
            canonical_name=asset.canonical_name,
            aliases=tuple(asset.aliases or ()),
            description=asset.description,
            base_traits=asset.base_traits,
            source_chapters=normalize_source_chapters(asset.source_chapters),
            metadata=MappingProxyType(
                {
                    key: str(value)
                    for key, value in metadata.items()
                    if key in {"role", "reference_layout"} and value is not None
                }
            ),
        )
