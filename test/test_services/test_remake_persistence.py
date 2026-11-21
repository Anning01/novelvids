import pytest
from tortoise.fields.relational import ManyToManyRelation

from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from services.remake.persistence import RemakeResultPersistence
from utils.enums import AssetTypeEnum, TaskStatusEnum, WorkflowStatus
from test.remake_fixtures import fixed_asset_prompt, synthetic_snapshot, remake_shot


@pytest.fixture(autouse=True)
def configured_asset_contract(monkeypatch):
    snapshot = synthetic_snapshot()
    monkeypatch.setattr('prompts.skill_pack.snapshot_skills', lambda: snapshot.model_dump())


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
            {"id": "character-001", "name": "将军", "label": "人物", "description": fixed_asset_prompt().replace('Modern city', description)}
        ],
        "scenes": [{"id": "scene-001", "name": "军帐", "description": fixed_asset_prompt(kind='scene')}],
        "objects": [{"id": "object-001", "name": "令牌", "description": fixed_asset_prompt(kind='item')}],
    }


def _prompt(index: int, *, refs=None, duration=4):
    return remake_shot(index, duration, refs=refs if refs is not None else [
        {'asset_id':'character-001','asset_name':'将军','asset_type':'character'},
        {'asset_id':'object-001','asset_name':'令牌','asset_type':'object'},
    ])


def _legacy_prompt(index: int):
    return {
        "shot_index": index,
        "file": f"scene-{index:03d}.mp4",
        "duration_seconds": 4,
        "asset_refs": [
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
    assert person.base_traits == _assets()['characters'][0]['description']
    assert person.source_chapters == [1]
    assert person.metadata["remake_reference_id"] == "character-001"
    scenes = await Scene.filter(chapter_id=source.chapter_id).order_by("sequence")
    assert all(f'专业镜头 {i}' in scene.prompt and '【核心生成指令｜高优先级】' in scene.prompt
               for i,scene in enumerate(scenes,1))
    assert scenes[0].metadata["remake_source_id"] == source.id
    assert {asset.canonical_name for asset in await scenes[0].assets.all()} == {"将军", "令牌", "军帐"}
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
    assert person.base_traits == _assets('更新后的将军')['characters'][0]['description']
    assert await scene.assets.all() == []
    assert scene.metadata["pipeline"]["attempt"] == 2


@pytest.mark.asyncio
async def test_persistence_rejects_free_text_before_any_assets_are_written():
    source = await _source()
    with pytest.raises(ValueError):
        await RemakeResultPersistence().persist(source=source, assets=_assets(),
            prompt_document={'prompts':[_legacy_prompt(1)]}, pipeline_metadata={})
    assert not await Asset.filter(novel_id=source.novel_id).exists()
    assert not await Scene.filter(chapter_id=source.chapter_id).exists()


@pytest.mark.asyncio
async def test_remade_group_keeps_group_layout_for_later_edits_and_image_generation():
    source = await _source()
    assets = _assets()
    assets['characters'][0].update(label='群像', description=fixed_asset_prompt(kind='group'))
    await RemakeResultPersistence().persist(source=source, assets=assets,
        prompt_document={'prompts':[_prompt(1)]}, pipeline_metadata={})
    group = await Asset.get(novel_id=source.novel_id, canonical_name='将军')
    assert group.metadata['reference_layout'] == 'group_portrait'


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
    assert person.base_traits == _assets('第一集描述')['characters'][0]['description']
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


@pytest.mark.asyncio
async def test_three_episode_binding_uses_scoped_aliases_and_preserves_user_fields():
    import asyncio
    from types import SimpleNamespace
    first = await _source()
    novel = await first.novel
    sources = [first]
    for i in (2, 3):
        chapter = await Chapter.create(novel=novel, number=i, name=str(i), content='')
        sources.append(SimpleNamespace(novel_id=novel.id, chapter_id=chapter.id, episode_number=i, id=first.id + i))
    hero = await Asset.create(novel=novel, asset_type=1, canonical_name='林澈', aliases=['将军'],
                              description='人工设定', base_traits='人工提示', main_image='/hero.png', metadata={'voice':'原音'})
    other = await Novel.create(name='其他项目')
    await Asset.create(novel=other, asset_type=1, canonical_name='将军', aliases=['林澈'])
    service = RemakeResultPersistence()
    catalog = await service.project_catalog(first)
    bound = [await service.bind_assets(first, _assets(), catalog)]
    seeded = await service.project_catalog(first)
    bound.extend(await asyncio.gather(*(service.bind_assets(s, _assets(), seeded) for s in reversed(sources[1:]))))
    assert [b['characters'][0]['project_asset_id'] for b in bound] == [hero.id] * 3
    assert all(b['characters'][0]['name'] == '林澈' for b in bound)
    assert len({b['objects'][0]['project_asset_id'] for b in bound}) == 1
    await hero.refresh_from_db()
    assert (hero.source_chapters, hero.description, hero.base_traits, hero.main_image, hero.metadata['voice']) == (
        [1,2,3], '人工设定', '人工提示', '/hero.png', '原音')
    assert len(catalog) == 1


@pytest.mark.asyncio
async def test_concurrently_introduced_same_name_with_different_evidence_keeps_two_identities():
    from types import SimpleNamespace
    source = await _source()
    service = RemakeResultPersistence()
    first = await service.bind_assets(source, _assets('青年男子'), [])
    chapter = await Chapter.create(novel_id=source.novel_id, number=2, name='第二集', content='')
    second = await service.bind_assets(SimpleNamespace(novel_id=source.novel_id, chapter_id=chapter.id, id=99, episode_number=2),
                                       _assets('白发老妇'), [])
    assert first['characters'][0]['project_asset_id'] != second['characters'][0]['project_asset_id']
    assert (await Asset.get(id=second['characters'][0]['project_asset_id'])).canonical_name == '将军 · EP2'


@pytest.mark.asyncio
async def test_named_outfits_reuse_subject_and_persist_the_confirmed_variant_on_the_shot():
    from models.asset_variant import AssetVariant
    source = await _source()
    svc = RemakeResultPersistence()
    candidates = _assets()
    candidates['characters'][0]['name'] = '将军（礼服形态）'
    bound = await svc.bind_assets(source, candidates, [])
    actor = bound['characters'][0]
    assert actor['name'] == '将军#礼服形态'
    variant = await AssetVariant.get(id=actor['project_variant_id'])
    assert variant.asset_id == actor['project_asset_id'] and variant.chapter_numbers == [1]
    await svc.persist(source=source, assets=bound, prompt_document={'prompts':[_prompt(1)]},pipeline_metadata={})
    scene = await Scene.get(chapter_id=source.chapter_id)
    assert scene.metadata['asset_variant_ids'][str(variant.asset_id)] == [variant.id]
