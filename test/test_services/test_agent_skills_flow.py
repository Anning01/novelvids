"""Two-chapter contract test. Provider doubles do not assert generation quality."""

from unittest.mock import AsyncMock

import pytest
from models.asset import Asset
from models.audio_reference import AudioReference
from models.chapter import Chapter
from models.config import AiModelConfig, GeneralConfig
from models.scene import Scene
from models.ai_task import AiTask
from models.video import Video
from controllers.novel import novel_controller
from controllers.chapter import chapter_controller
from controllers.asset import asset_controller
from controllers.scene import scene_controller
from controllers.video import video_controller
from schemas.video import VideoGenerateRequest
from schemas.scene import SoraScenePromptConfig, SceneEntity
from prompts.storyboard import format_storyboard_prompt
from services.storyboard.strategies import storyboard_strategy_factory
from services.ai_task_executor import ai_task_executor
from services.creation_agent.skill_execution import SkillExecution
from services.image_generation.gateway import GeneratedImage
from utils.enums import TaskStatusEnum
from test.test_services.test_skill_workflow import enabled_project
from test.test_services.test_prompt_language import _shot


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("screenplay_only", [False, True])
async def test_two_chapters_preserve_assets_prompts_and_voice_mapping(
    monkeypatch, language, tmp_path, screenplay_only
):
    novel, first, _ = await enabled_project()
    novel.storyboard_strategy = 'narration'
    novel.aspect_ratio = '16:9'
    second = await Chapter.create(
        novel=novel,
        number=2,
        name="The signal",
        content="Alex Chen and Sam Lee hear the signal.",
    )
    novel.content = "Chapter 1: Arrival\nAlex Chen meets Sam Lee.\nChapter 2: The signal\nThey hear the signal."
    if screenplay_only:
        novel.content = ""
        for chapter in (first, second):
            chapter.screenplay = chapter.content
            chapter.content = ""
            await chapter.save()
    await novel.save()
    await GeneralConfig.create(id=1, prompt_language=language)
    image_model = await AiModelConfig.create(
        name="image",
        task_type=2,
        model="image",
        api_key="test",
        base_url="https://image.invalid",
        image_model_type="seedream_5_lite",
        api_protocol="volcengine_ark",
        is_active=True,
    )
    video_model = await AiModelConfig.create(
        name="video",
        task_type=4,
        model="video",
        api_key="test",
        base_url="https://video.invalid",
        video_model_type="seedance_2",
        api_protocol="volcengine_ark",
        is_active=True,
    )
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    from test.test_services.test_asset_design_instructions import fixed_asset_prompt

    visual = fixed_asset_prompt(language, snapshot=SkillSnapshot.model_validate(snapshot_skills()),
                                ratio=novel.aspect_ratio)
    words = "信号。" if language == "zh" else "Signal."
    narrator = "旁白" if language == "zh" else "Narrator"
    seen = []
    storyboard_prompt = ""

    async def generate_strict(self, facts):
        nonlocal visual, storyboard_prompt
        assert self.language == language
        operation = self.params['output_contract']['name']
        seen.append((operation, language, self.params['creative_method']['revision']))
        if operation == 'story':
            if screenplay_only:
                assert first.screenplay in facts['manuscript'] and second.screenplay in facts['manuscript']
            return {'book_types': ['Drama'], 'story_outline': words, 'key_characters': []}
        if operation == 'assets':
            from services.extraction.strict_result import extraction_result
            fields = self.params['output_contract']['rendering']['asset_specifications']['person']['fields']
            payload = {'persons': [{'name': name, 'aliases': [], 'label': '人物', 'description': name,
                'design': 'A person in navy cotton clothes.', 'visual_fields': {key: 'Stable visual design' for key in fields},
                'variant': None} for name in ('Alex Chen', 'Sam Lee')], 'scenes': [], 'items': []}
            visual = extraction_result(payload, self.params['output_contract']['rendering']).persons[0].base_traits
            return payload
        if operation == 'storyboard':
            from services.storyboard.strict_result import storyboard_result
            shot = _shot().model_dump(exclude={'prompt', 'sequence', 'reference_only_types'})
            shot.update(duration=4, visible_asset_names=['Alex Chen', 'Sam Lee'],
                visual_prose='@{Alex Chen} meets @{Sam Lee}.',
                actions=[{'start': 0, 'end': 4, 'text': '@{Alex Chen} meets @{Sam Lee}.'}],
                dialogue=[{'start': 0, 'end': 1, 'speaker': 'Alex Chen', 'delivery': '', 'text': words},
                          {'start': 2, 'end': 3, 'speaker': 'Sam Lee', 'delivery': '', 'text': words}],
                narration=[{'start': 3, 'end': 4, 'speaker': narrator, 'delivery': '', 'text': words}])
            payload = {'shots': [shot]}
            storyboard_prompt = storyboard_result(payload, language,
                [SceneEntity.model_validate(value) for value in facts['entities']], storyboard_strategy_factory.resolve('narration')).shots[0].prompt
            return payload
        raise AssertionError(f'Unexpected generation: {operation}')

    monkeypatch.setattr(SkillExecution, 'generate_strict', generate_strict)
    monkeypatch.setattr(SkillExecution, 'generate', AsyncMock(side_effect=AssertionError('Unexpected legacy text generation')))
    image_calls = AsyncMock(
        return_value=[GeneratedImage(url="https://image.invalid/result.png")]
    )
    monkeypatch.setattr("services.reference.generator.generate_images", image_calls)
    monkeypatch.setattr(
        "services.reference.handler._persist_generated_image",
        AsyncMock(return_value="https://cdn.invalid/character.png"),
    )
    provider = AsyncMock()
    provider.submit.side_effect = ["episode-one", "episode-two"]
    provider.query.return_value = {
        "status": TaskStatusEnum.completed,
        "url": "https://video.invalid/result.mp4",
        "progress": 100,
        "metadata": {},
    }
    monkeypatch.setattr("controllers.video.get_generator", lambda config: provider)
    monkeypatch.setattr(
        "controllers.video._download_video", AsyncMock(return_value="/media/final.mp4")
    )
    monkeypatch.setattr(
        video_controller,
        "_compose_chapter",
        AsyncMock(return_value={"url": "/media/composed.mp4", "scene_count": 1}),
    )

    async def finish(task):
        await ai_task_executor.run(task)
        await task.refresh_from_db()
        assert task.status == 3, task.error_message

    await finish(await novel_controller.analyze(novel.id, include_cover=False))
    voices = [
        await AudioReference.create(
            nickname=name,
            gender="男",
            audio_url=f"https://audio.invalid/{index}.wav",
            avatar_url="",
            asset_id=f"voice-{index}",
        )
        for index, name in enumerate(("Alex Chen", "Sam Lee", narrator))
    ]
    novel.narrator_audio_reference_id = voices[2].id
    await novel.save()
    original_ids = None
    audio_orders = []
    for chapter in (first, second):
        await finish(await chapter_controller.extract(chapter.id))
        assets = await Asset.filter(novel=novel).order_by("id")
        if original_ids is None:
            original_ids = [asset.id for asset in assets]
            for asset, voice in zip(assets, voices):
                asset.metadata = {
                    **asset.metadata,
                    "voice_reference_id": voice.id,
                    "model_config_id": image_model.id,
                }
                await asset.save()
                await finish(await asset_controller.reference(asset.id))
        else:
            assert [asset.id for asset in assets] == original_ids
            assert [asset.metadata["voice_reference_id"] for asset in assets] == [
                voice.id for voice in voices[:2]
            ]
        await finish(await scene_controller.generate(chapter.id))
        scene = await Scene.get(chapter=chapter)
        assert scene.prompt == storyboard_prompt
        video = await video_controller.generate(
            VideoGenerateRequest(scene_id=scene.id, model_config_id=video_model.id)
        )
        task = await AiTask.get(id=video.metadata["agent_run_id"])
        await ai_task_executor.run(task)
        await task.refresh_from_db()
        assert task.stage == "waiting_media", task.error_message
        submitted = provider.submit.call_args.kwargs
        assert submitted["prompt"].startswith(storyboard_prompt)
        for track in [*scene.prompt_params['dialogue'], *scene.prompt_params['narration']]:
            assert track in submitted['prompt']
        assert "voice_bindings" in submitted["prompt"]
        assert "Alex Chen" in submitted["prompt"] and "Sam Lee" in submitted["prompt"]
        audio_orders.append(submitted["reference_audios"])
        completed = await video_controller.query_status(video.id)
        assert completed.status == 3
        merged = await video_controller.merge_chapter_videos(chapter.id)
        assert merged["url"] == "/media/composed.mp4"
    assert audio_orders[0] == audio_orders[1]
    assert len(audio_orders[0]) == 3
    assert await Video.all().count() == 2
    assert provider.submit.await_count == 2
    assert image_calls.await_count == 2
    assert all(call.kwargs["prompt"] == visual for call in image_calls.call_args_list)
    for operation in ('story', 'assets', 'storyboard'):
        assert len({revision for task, _, revision in seen if task == operation}) == 1
