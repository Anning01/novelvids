import pytest

from models.asset import Asset
from models.chapter import Chapter
from models.creation_agent import PromptChange
from models.novel import Novel
from models.scene import Scene
from schemas.creation_objects import CreationObjectQuery
from services.creation_agent.catalog import CreationCatalog
from services.creation_objects import CreationObjects, project_write
from test.test_services.test_creation_object_lifecycle import objects


@pytest.mark.asyncio
async def test_discovery_is_bounded_and_project_scoped_without_selected_targets():
    novel, chapter, asset, scenes = await objects()
    other = await Novel.create(name='别人的项目')
    await Asset.create(novel=other, canonical_name='私有角色', asset_type=1)
    catalog = CreationCatalog(novel.id, chapter.id)
    first = await catalog.search(CreationObjectQuery(page_size=2))
    second = await catalog.search(CreationObjectQuery(page_size=2, page=2))
    assert len(first['items']) == 2 and first['next_page'] == 2
    assert not {(r['kind'], r['id']) for r in first['items']} & {(r['kind'], r['id']) for r in second['items']}
    result = await catalog.search(CreationObjectQuery(kind='asset', asset_type=1))
    assert [item['id'] for item in result['items']] == [asset.id]
    assert not any('prompt' in item or 'base_traits' in item for item in result['items'])
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
async def test_other_chapter_details_are_bounded_and_project_scoped():
    novel, chapter, _, _ = await objects()
    second = await Chapter.create(novel=novel, number=2, name='清晨', content='甲' * 500 + '乙' * 500)
    catalog = CreationCatalog(novel.id, chapter.id)
    first = await catalog.read_chapter(second.id, 500, 0)
    assert first['content_excerpt'] == '甲' * 500
    assert first['content_truncated'] and first['content_next_offset'] == 500
    last = await catalog.read_chapter(second.id, 500, first['content_next_offset'])
    assert last['content_excerpt'] == '乙' * 500 and last['content_next_offset'] is None
    other = await Novel.create(name='隔离项目')
    forbidden = await Chapter.create(novel=other, number=1, name='私有章', content='私有正文')
    with pytest.raises(ValueError, match='不属于'):
        await catalog.read_chapter(forbidden.id, 500)
    other_chapter = await Chapter.create(novel=other, number=1, name='私有正文', content='不能泄露')
    with pytest.raises(ValueError, match='不属于'):
        await catalog.search(CreationObjectQuery(chapter_id=other_chapter.id))


@pytest.mark.asyncio
async def test_query_names_and_reference_pages_do_not_mutate_or_include_archives():
    novel, chapter, asset, scenes = await objects()
    for scene in scenes:
        await scene.assets.add(asset)
    catalog = CreationCatalog(novel.id, chapter.id)
    found = await catalog.search(CreationObjectQuery(kind='asset', search='林夏'))
    assert found['items'][0]['name'] == '林夏'
    assert found['items'][0]['reference_count'] == 3
    await Asset.filter(id=asset.id).update(aliases=['雨夜旅人'])
    aliased = await catalog.search(CreationObjectQuery(kind='asset', search='旅人'))
    assert [item['id'] for item in aliased['items']] == [asset.id]
    references = await catalog.references('asset', asset.id, page_size=2)
    assert references['total'] == 3 and references['next_page'] == 2
    async with project_write(novel.id):
        await CreationObjects(novel.id).archive('scene', scenes[0].id)
    assert (await catalog.references('asset', asset.id))['total'] == 2
    found = await catalog.search(CreationObjectQuery(kind='scene'))
    assert found['total'] == 2
    assert await PromptChange.all().count() == 0
