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
    _save_cover,
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


def test_project_analysis_accepts_prose_and_rejects_empty_visual_prompt():
    value = "young Chinese man, black hair, travel cloak"
    assert KeyCharacter(name="林舟", aliases=[], role="主角", description="寻找真相", base_traits=value, chapter_numbers=[1, 2]).base_traits == value
    with pytest.raises(ValidationError, match="must not be empty"):
        KeyCharacter(name="林舟", role="主角", description="寻找真相", base_traits="  ")


@pytest.mark.asyncio
async def test_project_analysis_uses_configured_image_protocol_for_cover():
    novel = await Novel.create(
        name="山海归途",
        content="第1章 启程\n林舟离开故乡。\n第2章 归途\n林舟揭开旧日真相。",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.project_analysis.value,
        task_types=[AiTaskTypeEnum.project_analysis.value],
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
        image_model_type="seedream_5_pro",
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
    assert [chapter.name for chapter in chapters] == ["启程", "归途"]
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
    assert STRUCTURED_PERSON_TRAITS in character.base_traits
    assert character.metadata["role"] == "主角"
    assert character.metadata["reference_layout"] == "character_turnaround"

    messages = llm_client.create.await_args.kwargs["messages"]
    system_prompt = messages[0]["content"]
    from prompts.skill_pack import read_skill
    assert read_skill("story") in system_prompt
    assert read_skill("structured") in system_prompt
    assert "language=en" in system_prompt

    await novel.refresh_from_db()
    assert novel.cover == "/media/covers/test.png"
    assert novel.tags == ["东方奇幻", "冒险"]
    assert novel.story_outline == "林舟远行并在归途中揭开家族真相。"
    generate_images.assert_awaited_once()
    request = generate_images.await_args.kwargs
    assert request["api_protocol"] == "volcengine_ark"
    assert request["resolution"] == "1248x1872"
    assert request["aspect_ratio"] == "2:3"
    assert request["output_format"] == "png"


class FakeLlmClientWithUsage(FakeLlmClient):
    def __init__(self, analysis: BookAnalysis):
        super().__init__(analysis)
        self.create.return_value.usage = SimpleNamespace(
            prompt_tokens=200, completion_tokens=80, total_tokens=280
        )


@pytest.mark.asyncio
async def test_project_analysis_result_carries_billing_keys():
    novel = await Novel.create(name="计费分析", content="第1章 起\n林舟出发。")
    llm = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.project_analysis.value,
        task_types=[AiTaskTypeEnum.project_analysis.value],
        name="llm", base_url="https://llm.example.com", api_key="k", model="llm-model",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
        is_active=True,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image", base_url="https://image.example.com", api_key="k", model="img-model",
        api_protocol="volcengine_ark", image_model_type="seedream_5_pro",
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.10}},
        is_active=True,
    )
    analysis = BookAnalysis(
        book_types=["冒险"], story_outline="林舟出发。",
        key_characters=[KeyCharacter(
            name="林舟", aliases=[], role="主角", description="青年。",
            base_traits=STRUCTURED_PERSON_TRAITS, chapter_numbers=[1],
        )],
    )
    llm_client = FakeLlmClientWithUsage(analysis)
    generated_image = SimpleNamespace(url="https://example.com/cover.png", b64_json=None)

    with (
        patch("services.project_analysis.handler.AsyncOpenAI", return_value=llm_client),
        patch("services.project_analysis.handler.generate_images", new=AsyncMock(return_value=[generated_image])),
        patch("services.project_analysis.handler._save_cover", new=AsyncMock(return_value="/media/covers/c.png")),
    ):
        result = await ProjectAnalysisTaskHandler().execute({"novel_id": novel.id})

    assert result["token_usage"]["prompt_tokens"] == 200
    assert result["llm_config_id"] == llm.id
    assert result["llm_model"] == "llm-model"
    assert result["image_usage"] == {"image_count": 1, "clarity": "1.5K"}
    assert result["image_config_id"] is not None


@pytest.mark.asyncio
async def test_save_cover_uploads_to_oss_when_enabled(monkeypatch):
    """OSS 启用时，同时上传原图和两个带长期缓存的 WebP 派生图。"""
    from services.oss import base as oss_base

    class FakeOss(oss_base.OSSProvider):
        name = "fake"
        enabled = True
        uploaded = []

        async def put_bytes(self, key, data, content_type, *, cache_control=None):
            self.uploaded.append((key, data, content_type, cache_control))

        def public_url(self, key):
            return f"https://cdn.example.com/{key}"

    fake = FakeOss()
    monkeypatch.setattr("services.oss.oss", fake)

    import base64
    import cv2
    import numpy as np

    success, encoded = cv2.imencode(
        ".png",
        np.full((600, 400, 3), (40, 90, 180), dtype=np.uint8),
    )
    assert success
    original = encoded.tobytes()

    image = SimpleNamespace(
        url=None,
        b64_json=base64.b64encode(original).decode(),
    )
    url = await _save_cover(image, 9)

    assert len(fake.uploaded) == 3
    key, data, content_type, cache_control = fake.uploaded[0]
    assert key.startswith("uploads/0/")
    assert "novel-9-" in key
    assert data == original
    assert content_type == "image/png"
    assert cache_control is None
    derivatives = fake.uploaded[1:]
    assert {item[0].rsplit("-", 1)[-1] for item in derivatives} == {
        "thumbnail.webp",
        "preview.webp",
    }
    assert all(item[2] == "image/webp" for item in derivatives)
    assert all(item[3] == "public, max-age=31536000, immutable" for item in derivatives)
    # OSS 媒体持久化对象键，响应序列化时再签发临时访问 URL。
    assert url == key


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['missing_config', 'provider', 'save'])
@pytest.mark.parametrize('language', ['zh', 'en'])
async def test_optional_cover_failure_keeps_story_result_prior_cover_and_actual_usage(failure, language):
    novel = await Novel.create(name='可继续制作', content='第一章 归来\n林舟走回故乡。', cover='/media/existing.png')
    llm = await AiModelConfig.create(task_type=5, name='llm', model='test-llm', api_key='test-key', base_url='https://example.invalid', is_active=True)
    if failure != 'missing_config':
        await AiModelConfig.create(task_type=2, name='image', model='test-image', api_key='test-key', base_url='https://example.invalid', api_protocol='volcengine_ark', image_model_type='seedream_5_pro', is_active=True)
    analysis = BookAnalysis(book_types=['归乡'], story_outline='林舟返回故乡。', key_characters=[
        KeyCharacter(name='林舟', role='主角', description='归来的青年', base_traits=STRUCTURED_PERSON_TRAITS, chapter_numbers=[1]),
    ])
    generate = AsyncMock(side_effect=RuntimeError('provider rejects request')) if failure == 'provider' else AsyncMock(return_value=[SimpleNamespace(url='https://example.invalid/cover.png')])
    save = AsyncMock(side_effect=OSError('storage unavailable'))
    with patch('services.project_analysis.handler.AsyncOpenAI', return_value=FakeLlmClientWithUsage(analysis)), patch('services.project_analysis.handler.generate_images', generate), patch('services.project_analysis.handler._save_cover', save):
        result = await ProjectAnalysisTaskHandler().execute({'novel_id': novel.id, 'prompt_language': language})
    await novel.refresh_from_db()
    assert result['story_outline'] == novel.story_outline == analysis.story_outline
    assert result['cover'] == novel.cover == '/media/existing.png'
    assert ('可以继续' if language == 'zh' else 'ready to use') in result['cover_warning']
    assert result['analysis_completed'] is True
    assert result['cover_status'] == 'failed'
    assert result['token_usage']['prompt_tokens'] == 200
    assert result['llm_config_id'] == llm.id
    assert await Asset.filter(novel_id=novel.id, canonical_name='林舟').exists()
    if failure == 'save':
        assert result['image_usage']['image_count'] == 1
    else:
        assert 'image_usage' not in result
        save.assert_not_awaited()
    if failure == 'missing_config':
        generate.assert_not_awaited()


def test_project_analysis_templates_preserve_material_and_requested_language():
    import json
    from prompts.project_analysis import render_analysis_messages
    from prompts.skill_pack import read_skill
    for language in ("zh", "en"):
        messages = render_analysis_messages(name="雨夜来信", chapter_count=2, material="第一章 车站\n第二章 咖啡馆", prompt_language=language)
        assert messages[0]["content"].endswith(read_skill("story"))
        assert "language=" + language in messages[0]["content"]
        facts = json.loads(messages[1]["content"])["untrusted_task_facts"]
        assert facts == {"name": "雨夜来信", "chapter_count": 2, "manuscript": "第一章 车站\n第二章 咖啡馆"}
