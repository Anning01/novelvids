"""Language selection, immutable task snapshots and English voice contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_locale
from models.config import GeneralConfig
from models.novel import Novel
from models.chapter import Chapter
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.scene import Scene
from prompts.creation_agent import render_creation_instructions
from prompts.creation_standards import validate_storyboard_sections
from prompts.project_analysis import render_analysis_messages
from prompts.video import render_voice_reference_instruction
from prompts.storyboard import format_storyboard_prompt
from services.ai_task_executor import AiTaskExecutor
from services.language import configured_language, generation_language
from services.nlp import NovelText, RegexChapterRecognitionStrategy
from services.video.capabilities import capabilities_for
from services.video.content import prepare_video_content
from services.video.voice_references import resolve_voice_references
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message, message_language
from utils.prompt_language import task_language
from test.test_services.test_prompt_language import _shot


@pytest.mark.asyncio
async def test_public_locale_is_read_only_and_exposes_no_admin_configuration(client):
    before = await GeneralConfig.all().count()
    response = (await client.get("/api/config/locale")).json()
    assert response["code"] == 0
    assert response["data"] == {"locale": "en"}
    assert await GeneralConfig.all().count() == before
    await GeneralConfig.create(id=1, prompt_language="zh")
    assert (await get_locale()).data.model_dump() == {"locale": "zh"}
    assert await configured_language() == "zh"


@pytest.mark.asyncio
async def test_task_language_is_snapshotted_and_explicit_retry_language_is_retained():
    config = await GeneralConfig.create(id=1, prompt_language="en")
    executor = AiTaskExecutor()
    with patch("services.balance.ensure_solvent", new=AsyncMock()):
        first = await executor.submit(AiTaskTypeEnum.storyboard, {})
        config.prompt_language = "zh"
        await config.save()
        retry = await executor.submit(
            AiTaskTypeEnum.storyboard, dict(first.request_params)
        )
        second = await executor.submit(AiTaskTypeEnum.storyboard, {})
    assert (
        first.request_params["prompt_language"]
        == retry.request_params["prompt_language"]
        == "en"
    )
    assert second.request_params["prompt_language"] == "zh"


@pytest.mark.asyncio
async def test_concurrent_task_contexts_do_not_leak_language():
    async def run(language):
        token = task_language.set(language)
        try:
            await asyncio.sleep(0)
            return await generation_language(), localized_message("项目不存在")
        finally:
            task_language.reset(token)

    assert await asyncio.gather(run("en"), run("zh")) == [
        ("en", "Project not found"),
        ("zh", "项目不存在"),
    ]
    assert task_language.get() is None


def test_messages_translate_templates_without_translating_user_or_provider_values():
    token = message_language.set("en")
    try:
        detail = "Provider 原文 @{User} {p1}"
        assert (
            localized_message("视频供应商返回错误：{p1}{p2}", p1=detail, p2="")
            == "Video provider returned an error: " + detail
        )
    finally:
        message_language.reset(token)


@pytest.mark.parametrize("crud", [False, True])
def test_english_agent_instructions_have_no_chinese_reply_requirement(crud):
    instructions = render_creation_instructions(
        language="en", crud=crud, turn_limited=True
    )
    assert "reply in English" in instructions
    assert "使用简体中文" not in instructions
    assert "只用简体中文" not in instructions
    assert "等中文" not in instructions


def test_english_storyboard_is_editable_and_preserves_identity_and_user_text():
    shot = _shot()
    shot.dialogue = ["0s-2s: @{Alex Reed}: Stay here."]
    rendered = format_storyboard_prompt(shot, "en")
    assert "[Character / Prop / Location references]" in rendered
    assert "@{Alex Reed}: Stay here." in rendered
    assert shot.visual_prose in rendered
    validate_storyboard_sections(rendered)
    validate_storyboard_sections(rendered, rendered)


@pytest.mark.parametrize(
    "heading", ["Chapter 1: Arrival", "CHAPTER I — Arrival", "# Episode 1: Arrival"]
)
def test_english_chapters_are_split_without_a_model(heading):
    text = NovelText(f"{heading}\nAlex waits.\nChapter 2: Return\nMorgan arrives.")
    chapters = RegexChapterRecognitionStrategy().recognize(text)
    assert len(chapters) == 2
    assert chapters[0].content == "Alex waits."
    assert chapters[1].content == "Morgan arrives."


@pytest.mark.asyncio
async def test_uploaded_english_voices_survive_across_chapters_and_variant_overrides():
    voices = [
        await AudioReference.create(
            nickname=name,
            gender="未设置",
            asset_id=name,
            audio_url=f"https://example.test/{name}.wav",
            avatar_url="",
            source="upload",
            duration=3,
        )
        for name in ["alex", "morgan", "narrator"]
    ]
    novel = await Novel.create(
        name="The Signal", author="Test", narrator_audio_reference_id=voices[2].id
    )
    alex = await Asset.create(
        novel=novel,
        canonical_name="Alex Reed",
        asset_type=1,
        metadata={"voice_reference_id": voices[0].id},
    )
    morgan = await Asset.create(
        novel=novel,
        canonical_name="Morgan Lee",
        asset_type=1,
        metadata={"voice_reference_id": voices[1].id},
    )
    variant = await AssetVariant.create(
        asset=alex, name="Coat", metadata={"voice_reference_id": voices[0].id}
    )
    for number in [1, 2]:
        chapter = await Chapter.create(
            novel=novel,
            number=number,
            name=f"Chapter {number}",
            content="The signal returned.",
        )
        scene = await Scene.create(
            chapter=chapter,
            sequence=1,
            prompt="A quiet station.",
            duration=6,
            prompt_params={
                "narration": ["0s-1s: Narrator (calm): Night fell."],
                "dialogue": [
                    "1s-3s: @{Alex Reed}: Stay here.",
                    "3s-5s: @{Morgan Lee}: I will.",
                ],
            },
            metadata={"asset_variant_ids": {str(alex.id): variant.id}},
        )
        await scene.assets.add(alex, morgan)
        references = await resolve_voice_references(
            scene=scene,
            novel=novel,
            subjects=[],
            capabilities=capabilities_for("seedance_2"),
        )
        assert {item.reference_id for item in references} == {
            voice.id for voice in voices
        }
        assert references[0].kind == "narrator"
        audio_urls = [item.url for item in references]
        prompt = render_voice_reference_instruction(
            [
                {"index": i + 1, "kind": item.kind, "subjects": list(item.subjects)}
                for i, item in enumerate(references)
            ],
            language="en",
        )
        prepared = prepare_video_content(
            prompt=prompt,
            subjects=[],
            generation_mode="reference",
            max_reference_images=9,
            reference_audios=audio_urls,
        )
        assert [
            item["audio_url"]["url"]
            for item in prepared.items
            if item["type"] == "audio_url"
        ] == audio_urls
        assert "Narrator: use [音频1]" in prepared.prompt
        assert "Alex Reed" in prepared.prompt and "Morgan Lee" in prepared.prompt
        assert "narration in English" in prepared.prompt


@pytest.mark.asyncio
async def test_seedance_outbound_payload_preserves_english_dialogue_and_audio_order(
    monkeypatch,
):
    import httpx
    from services.video.seedance import SeedanceGenerator
    from models.config import AiModelConfig

    config = await AiModelConfig.create(
        task_type=4,
        name="English video",
        model="configured-model",
        base_url="https://provider.example.test/api/v3",
        api_key="test-only-key",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=True,
    )
    requests = []

    async def respond(request):
        import json

        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "english-video-task"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "services.video.seedance.httpx.AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    dialogue = "@{Alex Reed} (quiet): Stay here. @{Morgan Lee}: We go together."
    prompt = (
        dialogue
        + "\n"
        + render_voice_reference_instruction(
            [
                {"index": 1, "kind": "narrator", "subjects": ["Narrator"]},
                {
                    "index": 2,
                    "kind": "character",
                    "subjects": ["Alex Reed", "Morgan Lee"],
                },
            ],
            language="en",
        )
    )
    task = await SeedanceGenerator(config).submit(
        prompt=prompt,
        duration=6,
        generate_audio=True,
        reference_audios=[
            "https://example.test/narrator.wav",
            "https://example.test/shared.wav",
            "https://example.test/shared.wav",
        ],
    )
    assert task == "english-video-task"
    body = requests[0]
    assert body["generate_audio"] is True
    assert "Stay here." in body["content"][0]["text"]
    assert "Narrator: use [音频1]" in body["content"][0]["text"]
    assert "Alex Reed, Morgan Lee: use [音频2]" in body["content"][0]["text"]
    assert [
        item["audio_url"]["url"]
        for item in body["content"]
        if item["type"] == "audio_url"
    ] == ["https://example.test/narrator.wav", "https://example.test/shared.wav"]


def test_english_video_language_is_explicit_without_uploaded_voices():
    assert "narration in English" in render_voice_reference_instruction(
        [], language="en"
    )


def test_english_continuity_is_idempotent_and_does_not_rewrite_dialogue():
    from prompts.video import inject_last_frame_continuity_prompt

    original = "Alex: Keep the label 【首帧衔接】 in the note."
    first = inject_last_frame_continuity_prompt(
        original, "@{参考图片:https://example.test/one.png}", "en"
    )
    second = inject_last_frame_continuity_prompt(
        first, "@{参考图片:https://example.test/two.png}", "en"
    )
    assert second.count("[First-frame continuity]") == 1
    assert "one.png" not in second and "two.png" in second
    assert original in second


def test_english_legacy_reference_only_edit_retains_other_assets_and_voice_tracks():
    from prompts.storyboard import without_inline_reference_descriptions
    from prompts.creation_agent import render_preserved_tracks
    original = (
        '[Character / Prop / Location references]\n'
        'Character references：@{Alex Reed}\n'
        'Character design：@{Alex Reed}。A brown coat.\n'
        'Prop references：@{Key}\n'
        'Prop design：@{Key}。A brass key.\n'
        '[Shot description]\nAlex looks up.'
    )
    result = without_inline_reference_descriptions(original, ['人物'])
    assert 'A brown coat.' not in result
    assert 'Character references：@{Alex Reed}' in result
    assert 'A brass key.' in result
    rendered = render_preserved_tracks(result, {'prompt_language': 'en', 'dialogue': ['Alex: Stay here.']})
    assert '[Character dialogue]' in rendered and 'Alex: Stay here.' in rendered
    assert render_preserved_tracks(rendered, {'prompt_language': 'en', 'dialogue': ['Alex: Stay here.']}) == rendered
