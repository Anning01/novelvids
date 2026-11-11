import pytest

from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from schemas.scene import SceneEntity, SoraScenePromptConfig, Storyboard
from services.storyboard.handler import StoryboardTaskHandler
from utils.enums import AssetTypeEnum


def _shot(sequence: int = 1, visual_prose: str = "@{张三} 推门而入。") -> SoraScenePromptConfig:
    return SoraScenePromptConfig(
        sequence=sequence,
        description="夜访",
        duration="4s",
        shot_size_and_camera="中景正面机位",
        visual_style="冷色写实",
        effect_restrictions=["禁止廉价发光特效"],
        time_setting="深夜",
        environment="湿冷夜风",
        spatial_relationships="人物从左侧接近",
        visual_prose=visual_prose,
        actions=[f"0.0s-4.0s: 镜头缓慢接近 {visual_prose}"],
        format_and_look="180° 快门",
        lenses_and_filtration="35mm 球面",
        lighting_and_atmosphere="冷色月光",
        grade_and_palette="青灰阴影",
        camera_movement="缓慢推镜",
        sound_design="夜风",
        dialogue=[],
        transition="承接下一镜头",
        allowed_effects=[],
    )


@pytest.mark.asyncio
async def test_save_scenes_persists_referenced_assets():
    novel = await Novel.create(name="分镜持久化测试")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第一章", content="正文")
    person = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
        aliases=[],
    )
    unused = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.item.value,
        canonical_name="旧钥匙",
        aliases=[],
    )

    entities = [
        SceneEntity(
            name=person.canonical_name,
            aliases=person.aliases or [],
            description=person.description or "",
            asset_type=AssetTypeEnum(person.asset_type).nickname,
            asset_id=person.id,
        ),
        SceneEntity(
            name=unused.canonical_name,
            aliases=unused.aliases or [],
            description=unused.description or "",
            asset_type=AssetTypeEnum(unused.asset_type).nickname,
            asset_id=unused.id,
        ),
    ]

    storyboard = Storyboard(shots=[_shot(1)])
    scenes = await StoryboardTaskHandler()._save_scenes(
        chapter_id=chapter.id,
        storyboard=storyboard,
        api_metadata={},
        request_duration=0.0,
        prompt_language="zh",
        entities=entities,
    )

    assert len(scenes) == 1
    await scenes[0].fetch_related("assets")
    linked_ids = {asset.id for asset in scenes[0].assets}
    assert linked_ids == {person.id}


@pytest.mark.asyncio
async def test_save_scenes_normalizes_plain_person_names_before_persisting():
    novel = await Novel.create(name="人物引用兜底测试")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第一章", content="正文")
    person = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李七夜",
        aliases=["李公子"],
    )
    entity = SceneEntity(
        name=person.canonical_name,
        aliases=person.aliases or [],
        description="",
        asset_type="人物",
        asset_id=person.id,
    )
    shot = _shot(1, "李七夜从泥水中起身。")
    shot.spatial_relationships = "李公子位于画面中央。"
    shot.dialogue = ["李七夜（惊呼）：我的身体！"]

    scenes = await StoryboardTaskHandler()._save_scenes(
        chapter_id=chapter.id,
        storyboard=Storyboard(shots=[shot]),
        api_metadata={},
        request_duration=0.0,
        prompt_language="zh",
        entities=[entity],
    )

    scene = scenes[0]
    await scene.fetch_related("assets")
    assert {asset.id for asset in scene.assets} == {person.id}
    assert scene.description == "夜访"
    assert scene.prompt_params["visual_prose"] == "@{李七夜}从泥水中起身。"
    assert scene.prompt_params["spatial_relationships"] == "@{李七夜}位于画面中央。"
    assert scene.prompt_params["dialogue"] == ["@{李七夜}（惊呼）：我的身体！"]
    assert "角色参考：@{李七夜}" in scene.prompt


@pytest.mark.asyncio
async def test_save_scenes_persists_narration_strategy_and_voice_track():
    novel = await Novel.create(name="旁白分镜持久化测试")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第一章",
        content="正文",
    )
    shot = _shot(1)
    shot.narration = ["0.0s-1.5s: 旁白（克制）：风暴正在逼近。"]
    shot.dialogue = ["2.0s-3.0s: @{张三}（低声）：快走。"]

    scenes = await StoryboardTaskHandler()._save_scenes(
        chapter_id=chapter.id,
        storyboard=Storyboard(shots=[shot]),
        api_metadata={},
        request_duration=0.0,
        storyboard_strategy="narration",
    )

    scene = scenes[0]
    assert scene.prompt_params["narration"] == shot.narration
    assert scene.metadata["storyboard_strategy"] == "narration"
    assert scene.metadata["storyboard_strategy_name"] == "旁白叙事"
    assert "【旁白 / 内心 OS】" in scene.prompt
    assert "【禁止项】\n禁止廉价发光特效" in scene.prompt and shot.sound_design in scene.prompt


@pytest.mark.asyncio
async def test_shots_persist_ai_selected_variant_and_explicit_base_for_flashback():
    from models.asset_variant import AssetVariant
    from services.storyboard.entities import generation_entities_for_assets
    from services.video.asset_resolver import select_asset_variant, normalize_selected_variant_ids

    novel = await Novel.create(name='分镜形态绑定')
    chapter = await Chapter.create(novel=novel, number=2, name='第二章', content='成长与回忆')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='张三', base_traits='少年')
    variant = await AssetVariant.create(asset=asset, name='成年', base_traits='成年', chapter_numbers=[2])
    loaded = await Asset.filter(id=asset.id).prefetch_related('variants')
    entities = generation_entities_for_assets(loaded, 2, {})
    scenes = await StoryboardTaskHandler()._save_scenes(chapter.id,
        Storyboard(shots=[_shot(1, '@{张三#成年} 推门。'), _shot(2, '@{张三} 在少年时读书。')]),
        {}, 0, entities=entities)
    assert scenes[0].metadata['asset_variant_ids'] == {str(asset.id): variant.id}
    assert scenes[1].metadata['asset_variant_ids'] == {str(asset.id): None}
    assert '@{张三#成年}' in scenes[0].prompt
    for scene, expected in zip(scenes, (variant.id, None)):
        await scene.fetch_related('assets')
        assert [row.id for row in scene.assets] == [asset.id]
        selected = select_asset_variant(loaded[0], 2, normalize_selected_variant_ids(scene.metadata['asset_variant_ids']))
        assert (selected.id if selected else None) == expected


@pytest.mark.asyncio
async def test_execute_passes_all_visual_forms_to_model_without_a_creation_plan(monkeypatch):
    from unittest.mock import AsyncMock
    from models.asset_variant import AssetVariant
    from prompts.storyboard import build_storyboard_messages

    novel = await Novel.create(name='分镜模型形态上下文')
    chapter = await Chapter.create(novel=novel, number=2, name='第二章', content='张三长大后拜入新宗门。')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='张三',
        base_traits='少年布衣', source_chapters=[1, 2])
    variant = await AssetVariant.create(asset=asset, name='成年宗门服', base_traits='成年青袍', chapter_numbers=[2])
    async def generate(**kwargs):
        entities = kwargs['entities']
        assert [entity.name for entity in entities] == ['张三', '张三#成年宗门服']
        messages = build_storyboard_messages(chapter.content, entities, 'zh')
        rendered = '\n'.join(message['content'] for message in messages)
        assert '成年青袍' in rendered and 'chapter_numbers' in rendered
        assert '回忆、闪回应选当时的形象' in rendered
        return Storyboard(shots=[_shot(1, '@{张三#成年宗门服} 拜入新宗门。')]), {}
    monkeypatch.setattr('services.storyboard.handler.generate_storyboard', generate)
    monkeypatch.setattr('services.storyboard.handler.AsyncOpenAI', lambda **kwargs: AsyncMock())
    summary = await StoryboardTaskHandler().execute({'chapter_id': chapter.id,
        'base_url': 'https://example.invalid', 'api_key': 'test', 'model': 'test'})
    from models.scene import Scene
    scene = await Scene.get(id=summary['scene_ids'][0])
    assert scene.metadata['asset_variant_ids'] == {str(asset.id): variant.id}


@pytest.mark.asyncio
async def test_same_identity_forms_can_be_saved_in_one_scene():
    from models.asset_variant import AssetVariant
    from models.scene import Scene
    from services.storyboard.entities import generation_entities_for_assets

    novel = await Novel.create(name='形态冲突不部分保存')
    chapter = await Chapter.create(novel=novel, number=2, name='第二章', content='正文')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='张三', base_traits='少年')
    await AssetVariant.create(asset=asset, name='成年', base_traits='成年', chapter_numbers=[2])
    entities = generation_entities_for_assets(await Asset.filter(id=asset.id).prefetch_related('variants'), 2, {})
    result = await StoryboardTaskHandler()._save_scenes(chapter.id, Storyboard(shots=[
        _shot(1), _shot(2, '@{张三} 和 @{张三#成年} 同时出现。')]), {}, 0, entities=entities)
    assert len(result) == 2
    scene = await Scene.filter(chapter=chapter, sequence=2).prefetch_related('assets').get()
    assert [item.id for item in scene.assets] == [asset.id]
    assert (scene.metadata or {}).get('asset_variant_ids', {}) == {}
    assert '@{张三#成年}' in scene.prompt
