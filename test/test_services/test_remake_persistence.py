import pytest
from tortoise.fields.relational import ManyToManyRelation

from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from services.remake.persistence import RemakeResultPersistence
from utils.enums import AssetTypeEnum, TaskStatusEnum, WorkflowStatus


async def _source() -> RemakeSource:
    novel = await Novel.create(
        name="重制持久化",
        author="tester",
        description="",
        content="",
        total_chapters=1,
        workflow_kind="remake",
    )
    chapter = await Chapter.create(
        novel=novel,
        number=1,
        name="第1集",
        content="",
    )
    return await RemakeSource.create(
        novel=novel,
        chapter=chapter,
        episode_number=1,
        source_kind="upload",
        storage_provider="local",
        object_key="remake/sources/source.mp4",
        original_filename="source.mp4",
        mime_type="video/mp4",
        size_bytes=100,
        duration_seconds=8,
        width=1280,
        height=720,
        container_format="mp4",
        checksum="a" * 64,
    )


def _assets(description="黑甲将军"):
    return {
        "characters": [
            {"id": "character-001", "name": "将军", "label": "人物", "description": description}
        ],
        "scenes": [{"id": "scene-001", "name": "军帐", "description": "深色军帐"}],
        "objects": [{"id": "object-001", "name": "令牌", "description": "黑木令牌"}],
    }


def _prompt(index: int, *, refs=None, duration=4):
    return {
        "shot_index": index,
        "file": f"scene-{index:03d}.mp4",
        "duration_seconds": duration,
        "asset_refs": refs
        if refs is not None
        else [
            {"asset_id": "character-001", "asset_name": "将军", "asset_type": "character"},
            {"asset_id": "object-001", "asset_name": "令牌", "asset_type": "object"},
        ],
        "prompt": f"专业镜头 {index}",
        "confidence": 0.9,
    }


@pytest.mark.asyncio
async def test_persistence_maps_assets_scenes_and_references_atomically():
    source = await _source()
    service = RemakeResultPersistence()

    summary = await service.persist(
        source=source,
        assets=_assets(),
        prompt_document={"prompts": [_prompt(1), _prompt(2)]},
        pipeline_metadata={"pipeline": "global_assets_professional_prompts_v4"},
    )

    assert summary == {"asset_count": 3, "scene_count": 2}
    persisted = await Asset.filter(novel_id=source.novel_id).order_by("asset_type")
    assert [item.asset_type for item in persisted] == [
        AssetTypeEnum.person.value,
        AssetTypeEnum.scene.value,
        AssetTypeEnum.item.value,
    ]
    assert AssetTypeEnum.product.value not in [item.asset_type for item in persisted]
    person = persisted[0]
    assert person.base_traits == "黑甲将军"
    assert person.source_chapters == [1]
    assert person.metadata["remake_reference_id"] == "character-001"
    scenes = await Scene.filter(chapter_id=source.chapter_id).order_by("sequence")
    assert [scene.prompt for scene in scenes] == ["专业镜头 1", "专业镜头 2"]
    assert scenes[0].metadata["remake_source_id"] == source.id
    assert {asset.canonical_name for asset in await scenes[0].assets.all()} == {"将军", "令牌"}
    chapter = await Chapter.get(id=source.chapter_id)
    await source.refresh_from_db()
    assert chapter.status == TaskStatusEnum.completed.value
    assert chapter.workflow_status == WorkflowStatus.storyboard_ready.value
    assert source.media_status == "completed"


@pytest.mark.asyncio
async def test_persistence_retry_updates_owned_rows_without_duplicates_or_stale_scenes():
    source = await _source()
    service = RemakeResultPersistence()
    await service.persist(
        source=source,
        assets=_assets(),
        prompt_document={"prompts": [_prompt(1), _prompt(2)]},
        pipeline_metadata={"attempt": 1},
    )

    await service.persist(
        source=source,
        assets=_assets("更新后的将军"),
        prompt_document={"prompts": [_prompt(1, refs=[])]},
        pipeline_metadata={"attempt": 2},
    )

    assert await Asset.filter(novel_id=source.novel_id).count() == 3
    assert await Scene.filter(chapter_id=source.chapter_id).count() == 1
    person = await Asset.get(novel_id=source.novel_id, canonical_name="将军")
    scene = await Scene.get(chapter_id=source.chapter_id, sequence=1)
    assert person.base_traits == "更新后的将军"
    assert await scene.assets.all() == []
    assert scene.metadata["pipeline"]["attempt"] == 2


@pytest.mark.asyncio
async def test_persistence_does_not_overwrite_preexisting_user_asset():
    source = await _source()
    existing = await Asset.create(
        novel_id=source.novel_id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="将军",
        description="用户描述",
        base_traits="用户设定",
        metadata={"created_by": "user"},
    )

    await RemakeResultPersistence().persist(
        source=source,
        assets=_assets("模型描述"),
        prompt_document={"prompts": [_prompt(1)]},
        pipeline_metadata={},
    )

    await existing.refresh_from_db()
    assert existing.description == "用户描述"
    assert existing.base_traits == "用户设定"
    assert existing.metadata["created_by"] == "user"


@pytest.mark.asyncio
async def test_persistence_merges_cross_episode_assets_and_tracks_each_source():
    first = await _source()
    novel = await Novel.get(id=first.novel_id)
    second_chapter = await Chapter.create(
        novel=novel,
        number=2,
        name="第2集",
        content="",
    )
    second = await RemakeSource.create(
        novel=novel,
        chapter=second_chapter,
        episode_number=2,
        source_kind="upload",
        storage_provider="local",
        object_key="remake/sources/source-2.mp4",
        original_filename="source-2.mp4",
        mime_type="video/mp4",
        size_bytes=100,
        duration_seconds=8,
        width=1280,
        height=720,
        container_format="mp4",
        checksum="b" * 64,
    )
    service = RemakeResultPersistence()
    await service.persist(
        source=first,
        assets=_assets("第一集描述"),
        prompt_document={"prompts": [_prompt(1)]},
        pipeline_metadata={"episode": 1},
    )
    await service.persist(
        source=second,
        assets=_assets("第二集描述"),
        prompt_document={"prompts": [_prompt(1)]},
        pipeline_metadata={"episode": 2},
    )

    person = await Asset.get(novel=novel, canonical_name="将军")
    assert person.source_chapters == [1, 2]
    assert person.metadata["remake_source_ids"] == [first.id, second.id]
    assert person.base_traits == "第一集描述"
    first_scene = await Scene.get(chapter_id=first.chapter_id, sequence=1)
    second_scene = await Scene.get(chapter_id=second.chapter_id, sequence=1)
    assert person.id in [asset.id for asset in await first_scene.assets.all()]
    assert person.id in [asset.id for asset in await second_scene.assets.all()]


@pytest.mark.asyncio
async def test_persistence_rolls_back_all_assets_and_scenes_when_reference_write_fails(
    monkeypatch,
):
    source = await _source()

    async def fail_add(self, *instances, using_db=None):
        raise RuntimeError("simulated relation failure")

    monkeypatch.setattr(ManyToManyRelation, "add", fail_add)

    with pytest.raises(RuntimeError, match="simulated relation failure"):
        await RemakeResultPersistence().persist(
            source=source,
            assets=_assets(),
            prompt_document={"prompts": [_prompt(1)]},
            pipeline_metadata={},
        )

    assert await Asset.filter(novel_id=source.novel_id).count() == 0
    assert await Scene.filter(chapter_id=source.chapter_id).count() == 0
    chapter = await Chapter.get(id=source.chapter_id)
    await source.refresh_from_db()
    assert chapter.status == TaskStatusEnum.pending.value
    assert chapter.workflow_status == WorkflowStatus.draft.value
    assert source.media_status == "ready"
