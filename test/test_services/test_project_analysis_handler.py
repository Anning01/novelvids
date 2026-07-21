from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from services.project_analysis.handler import (
    BookAnalysis,
    KeyCharacter,
    ProjectAnalysisTaskHandler,
)
from utils.enums import AiTaskTypeEnum, AssetTypeEnum


class FakeLlmClient:
    def __init__(self, analysis: BookAnalysis):
        create = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content=analysis.model_dump_json(),
                    refusal=None,
                ))]
            )
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=create)
        )


class FakeImageClient:
    def __init__(self):
        self.images = SimpleNamespace(
            generate=AsyncMock(
                return_value=SimpleNamespace(data=[SimpleNamespace(url="https://example.com/cover.png")])
            )
        )


@pytest.mark.asyncio
async def test_project_analysis_splits_extracts_characters_and_generates_1k_cover():
    novel = await Novel.create(
        name="山海归途",
        content="第1章 启程\n林舟离开故乡。\n第2章 归途\n林舟揭开旧日真相。",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm",
        base_url="https://llm.example.com",
        api_key="secret-llm",
        model="test-llm",
        is_active=True,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image",
        base_url="https://image.example.com",
        api_key="secret-image",
        model="test-image",
        is_active=True,
    )

    analysis = BookAnalysis(
        book_types=["东方奇幻", "冒险"],
        story_outline="林舟远行并在归途中揭开家族真相。",
        key_characters=[
            KeyCharacter(
                name="林舟",
                aliases=[],
                role="主角",
                description="执着寻找真相的青年。",
                base_traits="young Chinese man, black hair, travel cloak",
                chapter_numbers=[1, 2],
            )
        ],
    )
    llm_client = FakeLlmClient(analysis)
    image_client = FakeImageClient()

    with (
        patch(
            "services.project_analysis.handler.AsyncOpenAI",
            side_effect=[llm_client, image_client],
        ),
        patch(
            "services.project_analysis.handler._save_cover",
            new=AsyncMock(return_value="/media/covers/test.png"),
        ),
    ):
        result = await ProjectAnalysisTaskHandler().execute({"novel_id": novel.id})

    chapters = await Chapter.filter(novel_id=novel.id).order_by("number")
    assert [chapter.name for chapter in chapters] == ["第1章 启程", "第2章 归途"]
    assert result["book_types"] == ["东方奇幻", "冒险"]
    assert result["chapter_count"] == 2
    assert result["cover"] == "/media/covers/test.png"

    character = await Asset.get(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="林舟",
    )
    assert character.is_global is False
    assert character.source_chapters == [1, 2]
    assert character.metadata["role"] == "主角"

    await novel.refresh_from_db()
    assert novel.cover == "/media/covers/test.png"
    image_client.images.generate.assert_awaited_once()
    assert image_client.images.generate.await_args.kwargs["size"] == "1K"
