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
    assert "角色参考：李七夜" in scene.prompt
