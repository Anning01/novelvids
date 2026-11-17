import json
from copy import deepcopy
from types import MappingProxyType

import pytest


from services.extraction.context import (
    ChapterExtractionInput,
    ExtractionContext,
    KnownAssetSnapshot,
    NovelExtractionMetadata,
)
from services.extraction.messages import (
    ExtractionMessageBuilder,
    compress_chapter_numbers,
)


@pytest.fixture
def extraction_context() -> ExtractionContext:
    return ExtractionContext(
        novel=NovelExtractionMetadata(
            name="厄运之手",
            author=None,
            description="小说元信息标记：一部都市异能故事。",
            tags=("都市异能", "复仇"),
            story_outline="宫平获得能力并反抗压迫。",
            project_type="短剧",
            project_setting="现代都市。",
        ),
        assets=(
            KnownAssetSnapshot(
                id=1,
                asset_type=1,
                asset_type_name="人物",
                canonical_name="宫平",
                aliases=("宫先生",),
                description="获得能力的员工",
                base_traits="young Chinese man",
                source_chapters=(4, 1, 2, 3, 8, 10, 11),
                metadata=MappingProxyType({"role": "主角"}),
            ),
            KnownAssetSnapshot(
                id=2,
                asset_type=2,
                asset_type_name="场景",
                canonical_name="办公室",
                aliases=(),
                description=None,
                base_traits="modern office",
                source_chapters=(1,),
                metadata=MappingProxyType({}),
            ),
            KnownAssetSnapshot(
                id=3,
                asset_type=3,
                asset_type_name="物品",
                canonical_name="自行车",
                aliases=("黑色自行车",),
                description="停在门口的自行车",
                base_traits="black bicycle",
                source_chapters=(),
                metadata=MappingProxyType({"reference_layout": "prop"}),
            ),
        ),
        chapter=ChapterExtractionInput(
            id=7,
            number=12,
            name="能力觉醒",
            content="章节正文唯一标记：宫平离开办公室，骑上自行车。",
        ),
    )






def test_builder_serializes_only_snapshot_fields_compactly_and_omits_empty_values(
    extraction_context: ExtractionContext,
):
    facts = ExtractionMessageBuilder().build(extraction_context)
    # Serialization preserves immutable snapshot values without injecting prompt rules.
    facts = json.loads(json.dumps(facts, ensure_ascii=False))
    novel_payload, asset_payload, chapter_payload = facts['project'], facts['known_assets'], facts['chapter']
    assert novel_payload == {
        "name": "厄运之手",
        "description": "小说元信息标记：一部都市异能故事。",
        "tags": ["都市异能", "复仇"],
        "story_outline": "宫平获得能力并反抗压迫。",
        "project_type": "短剧",
        "project_setting": "现代都市。",
    }
    assert len(asset_payload) == 3
    assert asset_payload[0] == {
        "id": 1,
        "asset_type": 1,
        "asset_type_name": "人物",
        "canonical_name": "宫平",
        "aliases": ["宫先生"],
        "description": "获得能力的员工",
        "base_traits": "young Chinese man",
        "source_chapters": "1-4,8,10-11",
        "metadata": {"role": "主角"},
    }
    assert "aliases" not in asset_payload[1]
    assert "description" not in asset_payload[1]
    assert "metadata" not in asset_payload[1]
    assert "source_chapters" not in asset_payload[2]
    assert chapter_payload == {
        "id": 7,
        "number": 12,
        "name": "能力觉醒",
        "content": extraction_context.chapter.content,
    }
    assert set(facts) == {"project", "known_assets", "chapter"}




def test_compress_chapter_numbers_sorts_deduplicates_and_groups_ranges():
    assert compress_chapter_numbers((1, 2, 3, 4, 8, 10, 11)) == "1-4,8,10-11"
    assert compress_chapter_numbers((4, 2, 3, 3, 1)) == "1-4"
    assert compress_chapter_numbers(()) == ""
