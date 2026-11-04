from unittest.mock import AsyncMock
import pytest
from tortoise import Tortoise
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.config import AiModelConfig
from schemas.video_defaults import ApplyVideoDefaults, VideoDefaults
from services.video_defaults import apply_defaults
from auth.deps import AuthContext


async def setup_project():
    novel = await Novel.create(name='Defaults')
    chapter = await Chapter.create(novel=novel, number=1, name='First', content='Story')
    config = await AiModelConfig.create(task_type=4, name='Video', model='test', api_key='test',
        base_url='https://example.test', api_protocol='volcengine_ark', video_model_type='seedance_2_mini', is_active=True)
    settings = VideoDefaults(model_config_id=config.id, resolution='480p', aspect_ratio='16:9', return_last_frame=True)
    return novel, chapter, settings


@pytest.mark.asyncio
async def test_apply_only_updates_parameters_and_remembers_defaults_without_generating():
    from models.ai_task import AiTask
    novel, chapter, settings = await setup_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='Keep edited prompt',
        metadata={'asset_variant_ids': {'1': 2}, 'current_video_id': 41})
    other_chapter = await Chapter.create(novel=novel, number=2, name='Second', content='More')
    other = await Scene.create(chapter=other_chapter, sequence=1, metadata={'video_resolution': '720p'})
    response = await apply_defaults(novel.id, ApplyVideoDefaults(chapter_id=chapter.id, settings=settings), AuthContext())
    await scene.refresh_from_db(); await other.refresh_from_db(); await novel.refresh_from_db()
    assert response['scene_count'] == 1 and response['remembered']
    assert scene.prompt == 'Keep edited prompt'
    assert scene.metadata['asset_variant_ids'] == {'1': 2} and scene.metadata['current_video_id'] == 41
    assert scene.metadata['return_last_frame'] is True and scene.metadata['auto_enhancement'] is None
    assert novel.video_generation_defaults == settings.model_dump(mode='json')
    assert other.metadata == {'video_resolution': '720p'}
    assert await AiTask.all().count() == 0
    await Tortoise.generate_schemas(safe=True)
    assert (await Novel.get(id=novel.id)).video_generation_defaults == settings.model_dump(mode='json')


@pytest.mark.asyncio
async def test_invalid_settings_and_foreign_chapters_do_not_partially_update():
    from fastapi import HTTPException
    novel, chapter, settings = await setup_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='Original')
    with pytest.raises(HTTPException):
        await apply_defaults(novel.id, ApplyVideoDefaults(chapter_id=chapter.id,
            settings=settings.model_copy(update={'resolution': 'invalid'})), AuthContext())
    other = await Novel.create(name='Other')
    with pytest.raises(HTTPException):
        await apply_defaults(other.id, ApplyVideoDefaults(chapter_id=chapter.id, settings=settings), AuthContext())
    await scene.refresh_from_db(); await novel.refresh_from_db()
    assert not scene.metadata and novel.video_generation_defaults is None


@pytest.mark.asyncio
async def test_not_remembering_preserves_project_defaults_and_api_returns_persisted_settings(client):
    novel, chapter, settings = await setup_project()
    await Scene.create(chapter=chapter, sequence=1)
    response = await client.post(f'/api/novel/{novel.id}/video-defaults', json={
        'chapter_id': chapter.id, 'settings': settings.model_dump(mode='json'), 'remember': False})
    assert response.json()['code'] == 0
    assert (await Novel.get(id=novel.id)).video_generation_defaults is None
    await client.post(f'/api/novel/{novel.id}/video-defaults', json={
        'chapter_id': chapter.id, 'settings': settings.model_dump(mode='json'), 'remember': True})
    response = await client.get(f'/api/novel/{novel.id}/meta')
    assert response.json()['data']['video_generation_defaults'] == settings.model_dump(mode='json')


@pytest.mark.asyncio
async def test_postgres_adds_only_nullable_preference_column(monkeypatch):
    from services.schema_compat import ensure_novel_analysis_schema
    db = AsyncMock()
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: db)
    monkeypatch.setattr('services.schema_compat.settings.DATABASE_URL', 'postgres://test')
    await ensure_novel_analysis_schema(); await ensure_novel_analysis_schema()
    assert db.execute_script.await_count == 2
    script = db.execute_script.await_args.args[0]
    assert 'IF NOT EXISTS video_generation_defaults JSONB' in script
    assert 'DROP' not in script and 'DELETE' not in script


@pytest.mark.parametrize('value,expected', [('480p', 480), ('768P', 768), ('1080p', 1080), ('2K', 1440), ('4k', 2160), ('unknown', None)])
def test_generation_resolution_labels_use_the_same_short_side_boundary(value, expected):
    from services.video_enhancement.contract import resolution_short_side
    assert resolution_short_side(value) == expected


@pytest.mark.asyncio
async def test_old_sqlite_data_survives_real_add_column_and_repeated_start(monkeypatch):
    import sqlite3
    from services.schema_compat import ensure_novel_analysis_schema
    database = sqlite3.connect(':memory:')
    database.row_factory = sqlite3.Row
    database.execute('CREATE TABLE novels (id INTEGER PRIMARY KEY, name TEXT, content TEXT)')
    database.execute('INSERT INTO novels VALUES (1, ?, ?)', ('Existing title', 'Existing manuscript'))
    class Connection:
        async def execute_query_dict(self, sql):
            return [dict(row) for row in database.execute(sql)]
        async def execute_script(self, sql):
            database.executescript(sql)
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: Connection())
    monkeypatch.setattr('services.schema_compat.settings.DATABASE_URL', 'sqlite://legacy-test')
    try:
        await ensure_novel_analysis_schema(); await ensure_novel_analysis_schema()
        row = database.execute('SELECT * FROM novels WHERE id=1').fetchone()
        assert row['name'] == 'Existing title' and row['content'] == 'Existing manuscript'
        assert row['video_generation_defaults'] is None
        assert database.execute('SELECT count(*) FROM novels').fetchone()[0] == 1
    finally:
        database.close()
