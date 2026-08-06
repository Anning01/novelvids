from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

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
        self.create = create


STRUCTURED_PERSON_TRAITS = """**时代基底**: modern
**国家/朝代**: China
**人种**: Chinese
**类型基底**: realistic
**脸型**: oval face, calm dark eyes
**发型**: straight black hair
**耳饰**: does not wear earrings
**身材**: lean, medium height
**头身比**: realistic seven-and-a-half-head proportion
**上身着装**: dark cotton travel cloak
**下身着装**: fitted black trousers
**鞋子**: worn brown leather boots
**性别**: male
**年龄**: young adult"""


def test_project_analysis_rejects_freeform_character_visual_traits():
    with pytest.raises(ValidationError, match="14项"):
        KeyCharacter(
            name="林舟",
            aliases=[],
            role="主角",
            description="执着寻找真相的青年。",
            base_traits="young Chinese man, black hair, travel cloak",
            chapter_numbers=[1, 2],
        )


@pytest.mark.asyncio
async def test_project_analysis_uses_configured_image_protocol_for_cover():
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
        api_protocol="volcengine_ark",
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
                base_traits=STRUCTURED_PERSON_TRAITS,
                chapter_numbers=[1, 2],
            )
        ],
    )
    llm_client = FakeLlmClient(analysis)
    generated_image = SimpleNamespace(url="https://example.com/cover.png", b64_json=None)
    generate_images = AsyncMock(return_value=[generated_image])

    with (
        patch(
            "services.project_analysis.handler.AsyncOpenAI",
            return_value=llm_client,
        ),
        patch(
            "services.project_analysis.handler.generate_images",
            new=generate_images,
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
    assert character.last_updated_chapter == 0
    assert character.base_traits == STRUCTURED_PERSON_TRAITS
    assert character.metadata["role"] == "主角"

    messages = llm_client.create.await_args.kwargs["messages"]
    system_prompt = messages[0]["content"]
    assert "字段名和顺序不可改变、合并或省略" in system_prompt
    assert all(label in system_prompt for label in (
        "时代基底", "国家/朝代", "人种", "类型基底", "脸型", "发型", "耳饰",
        "身材", "头身比", "上身着装", "下身着装", "鞋子", "性别", "年龄",
    ))

    await novel.refresh_from_db()
    assert novel.cover == "/media/covers/test.png"
    assert novel.tags == ["东方奇幻", "冒险"]
    assert novel.story_outline == "林舟远行并在归途中揭开家族真相。"
    generate_images.assert_awaited_once()
    request = generate_images.await_args.kwargs
    assert request["api_protocol"] == "volcengine_ark"
    assert request["resolution"] == "2K"
    assert request["aspect_ratio"] == "2:3"
