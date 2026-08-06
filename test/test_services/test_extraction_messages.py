import json
from copy import deepcopy
from types import MappingProxyType

import pytest

from services.extraction.budget import (
    ContextBudgetExceededError,
    ContextBudgetPolicy,
)
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


def _serialized_payload(content: str, boundary: str) -> object:
    opening = f"<{boundary}>"
    closing = f"</{boundary}>"
    return json.loads(content.split(opening, 1)[1].split(closing, 1)[0])


def test_builder_separates_rules_novel_registry_and_chapter(
    extraction_context: ExtractionContext,
):
    messages = ExtractionMessageBuilder().build(
        extraction_context,
        prompt_language="zh",
    )

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "user",
        "user",
    ]
    assert "当前章节明确事实" in messages[0]["content"]
    assert "小说元信息" in messages[1]["content"]
    assert "都市异能" in messages[1]["content"]
    assert "全部已识别资产" in messages[2]["content"]
    assert all(
        name in messages[2]["content"] for name in ("宫平", "办公室", "自行车")
    )
    assert "只返回本章" in messages[3]["content"]
    assert extraction_context.chapter.content in messages[3]["content"]

    assert extraction_context.chapter.content not in "".join(
        message["content"] for message in messages[:3]
    )
    assert "https://asset.example/image.png" not in messages[2]["content"]
    assert "严格返回以下 JSON" not in "".join(
        message["content"] for message in messages
    )
    assert "```json" not in "".join(message["content"] for message in messages)


def test_builder_serializes_only_snapshot_fields_compactly_and_omits_empty_values(
    extraction_context: ExtractionContext,
):
    messages = ExtractionMessageBuilder().build(
        extraction_context,
        prompt_language="zh",
    )

    novel_payload = _serialized_payload(messages[1]["content"], "novel_metadata")
    asset_payload = _serialized_payload(messages[2]["content"], "asset_registry")
    chapter_payload = _serialized_payload(messages[3]["content"], "chapter_task")

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
    assert '": "' not in "".join(message["content"] for message in messages[1:])


def test_asset_registry_explains_identity_matching_and_current_chapter_filtering(
    extraction_context: ExtractionContext,
):
    registry = ExtractionMessageBuilder().build(
        extraction_context,
        prompt_language="zh",
    )[2]["content"]

    assert (
        "该注册表仅用于身份匹配和稳定视觉一致性。"
        "只有在当前章节满足提取条件的资产才能进入响应；"
        "命中标准名称或别名时沿用标准名称。"
    ) in registry


def test_compress_chapter_numbers_sorts_deduplicates_and_groups_ranges():
    assert compress_chapter_numbers((1, 2, 3, 4, 8, 10, 11)) == "1-4,8,10-11"
    assert compress_chapter_numbers((4, 2, 3, 3, 1)) == "1-4"
    assert compress_chapter_numbers(()) == ""


def test_budget_reports_per_message_and_total_characters(
    extraction_context: ExtractionContext,
):
    messages = ExtractionMessageBuilder().build(
        extraction_context,
        prompt_language="zh",
    )

    report = ContextBudgetPolicy(max_context_characters=100_000).validate(
        messages,
        asset_count=3,
        chapter_characters=len(extraction_context.chapter.content),
    )

    assert report.message_characters == tuple(
        len(item["content"]) for item in messages
    )
    assert report.total_characters == sum(len(item["content"]) for item in messages)


def test_budget_rejects_over_limit_context_without_mutating_messages(
    extraction_context: ExtractionContext,
):
    messages = ExtractionMessageBuilder().build(
        extraction_context,
        prompt_language="zh",
    )
    original_messages = deepcopy(messages)

    with pytest.raises(ContextBudgetExceededError, match="资产 3 个"):
        ContextBudgetPolicy(max_context_characters=10).validate(
            messages,
            asset_count=3,
            chapter_characters=len(extraction_context.chapter.content),
        )

    assert messages == original_messages


def test_unbounded_budget_never_guesses_a_limit_from_model_names():
    messages = [
        {
            "role": "user",
            "content": "gpt-4o-mini claude-3-5-sonnet deepseek-v3" * 10_000,
        }
    ]

    report = ContextBudgetPolicy(max_context_characters=None).validate(
        messages,
        asset_count=0,
        chapter_characters=0,
    )

    assert report.total_characters == len(messages[0]["content"])


@pytest.mark.parametrize("limit", [0, -1])
def test_budget_rejects_non_positive_configured_limits(limit: int):
    with pytest.raises(ValueError, match="上下文字符上限必须大于 0"):
        ContextBudgetPolicy(max_context_characters=limit)
