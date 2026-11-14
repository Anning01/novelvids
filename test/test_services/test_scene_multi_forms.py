import pytest

from controllers.scene import scene_controller
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.novel import Novel
from schemas.scene import SceneCreate, ScenePatch
from services.creation_objects import CreationObjects
from services.project_transfer.restore import LocalIds
from services.storyboard.entities import entities_for_assets
from services.video.asset_resolver import normalize_selected_variant_ids, resolve_assets


@pytest.mark.asyncio
async def test_scene_forms_survive_saving_reloading_and_generation_context():
    novel = await Novel.create(name='同时出镜')
    chapter = await Chapter.create(novel=novel, number=1, name='第一集', content='正文')
    asset = await Asset.create(novel=novel, canonical_name='苏玄', asset_type=1, main_image='https://example.test/base.png')
    young = await AssetVariant.create(asset=asset, name='少年', images=['https://example.test/young.png'])
    baby = await AssetVariant.create(asset=asset, name='婴儿', images=['https://example.test/baby.png'])
    bindings = {str(asset.id): [None, young.id, baby.id]}
    scene = await scene_controller.create(SceneCreate(chapter_id=chapter.id, sequence=1, asset_ids=[asset.id],
        prompt='@{苏玄} 同时出现。', metadata={'asset_variant_ids': bindings}))
    restored = await scene_controller.get(scene.id)
    assert restored.metadata['asset_variant_ids'] == bindings
    assert [row.id for row in await CreationObjects(novel.id).variant_references(young)] == [scene.id]
    loaded = await Asset.filter(id=asset.id).prefetch_related('variants')
    entities = entities_for_assets(loaded, 1, normalize_selected_variant_ids(bindings))
    assert [entity.name for entity in entities] == ['苏玄', '苏玄#少年', '苏玄#婴儿']
    assert [entity.variant_id for entity in entities] == [None, young.id, baby.id]
    # Removing a form retains the others, and a single legacy scalar still works.
    await scene_controller.patch(scene.id, ScenePatch(metadata={'asset_variant_ids': {str(asset.id): [None, baby.id]}}))
    restored = await scene_controller.get(scene.id)
    assert await CreationObjects(novel.id).variant_references(young) == []
    assert [row.id for row in await CreationObjects(novel.id).variant_references(baby)] == [scene.id]
    subjects = await resolve_assets(restored.prompt, novel.id, selected_asset_ids=[asset.id],
        selected_variant_ids=normalize_selected_variant_ids(restored.metadata['asset_variant_ids']))
    assert [subject['images'] for subject in subjects] == [[asset.main_image], baby.images]
    assert await resolve_assets('@{苏玄#少年}抬头', novel.id, selected_asset_ids=[asset.id],
        selected_variant_ids=normalize_selected_variant_ids({str(asset.id): [baby.id]})) == []
    await scene_controller.patch(scene.id, ScenePatch(metadata={'asset_variant_ids': {str(asset.id): baby.id}}))
    assert (await scene_controller.get(scene.id)).metadata['asset_variant_ids'] == {str(asset.id): baby.id}


@pytest.mark.asyncio
async def test_every_form_is_validated_even_when_the_first_form_is_valid():
    novel = await Novel.create(name='逐形态校验')
    other = await Novel.create(name='其他项目')
    asset = await Asset.create(novel=novel, canonical_name='苏玄', asset_type=1)
    foreign = await Asset.create(novel=other, canonical_name='其他角色', asset_type=1)
    form = await AssetVariant.create(asset=asset, name='少年')
    foreign_form = await AssetVariant.create(asset=foreign, name='异项目')
    objects = CreationObjects(novel.id)
    for invalid in ([None, form.id, foreign_form.id], [], [form.id, -1], [form.id, {}]):
        with pytest.raises(ValueError):
            await objects.validate_variant_bindings([asset.id], {str(asset.id): invalid})
    await objects.validate_variant_bindings([asset.id], {str(asset.id): [None, form.id]})


def test_project_transfer_remaps_every_form_and_preserves_explicit_base():
    ids = LocalIds()
    ids.add(Asset, 1, 101)
    ids.add(AssetVariant, 11, 111)
    ids.add(AssetVariant, 12, 112)
    assert ids.references({'asset_variant_ids': {'1': [None, 11, 12]}}) == {
        'asset_variant_ids': {'101': [None, 111, 112]}}


def test_work_package_can_bind_one_asset_more_than_once_with_distinct_forms():
    from pydantic import ValidationError
    from schemas.work_package import Shot

    payload = {'id': 'shot', 'scene_id': 'scene', 'name': '同框', 'description': '多个形态', 'duration': 6,
        'prompt': '苏玄与少年、婴儿同时出镜', 'visual': [
            {'asset_id': 'hero'}, {'asset_id': 'hero', 'variant_id': 'young'}, {'asset_id': 'hero', 'variant_id': 'baby'}]}
    assert len(Shot.model_validate(payload).visual) == 3
    with pytest.raises(ValidationError, match='出镜资产重复'):
        Shot.model_validate({**payload, 'visual': [payload['visual'][0], payload['visual'][0]]})
