import os
import re
import subprocess
import sys
from unittest.mock import Mock

import pytest


def test_additive_schema_initialization_preserves_legacy_and_story_data(tmp_path):
    script = '''
import asyncio
from tortoise import Tortoise
import models
from models.novel import Novel
from models.chapter import Chapter
from models.story_memory import StorySubject, StoryCommit, StoryFact, StorySnapshot
from services.schema_compat import ensure_story_memory_schema
from services.creation_agent.plan_sources import fingerprint
from services.story_memory.sources import source_snapshot
from uuid import uuid4
async def run():
    await Tortoise.init(db_url=__import__('os').environ['DATABASE_URL'], modules={'models': [f'models.{n}' for n in models.__all__]})
    await Tortoise.generate_schemas(safe=True)
    project = await Novel.create(name='legacy', story_outline='old outline', project_setting='old setting')
    chapter = await Chapter.create(novel=project, number=1, name='old chapter', content='old source', screenplay='old script')
    db = Tortoise.get_connection('default')
    # Simulate an installation predating the four new, empty tables.
    for model in (StorySnapshot, StoryFact, StoryCommit, StorySubject):
        await db.execute_script('DROP TABLE ' + model._meta.db_table)
    await ensure_story_memory_schema()
    subject = await StorySubject.create(novel=project, kind='world', name='world')
    source = await source_snapshot(project.id)
    commit = await StoryCommit.create(novel=project, request_id=uuid4(), status='accepted', source_hash=fingerprint(source), source_snapshot=source)
    await StorySnapshot.create(novel=project, commit=commit, data={'fact_ids': []})
    await Tortoise.close_connections()
    await Tortoise.init(db_url=__import__('os').environ['DATABASE_URL'], modules={'models': [f'models.{n}' for n in models.__all__]})
    await ensure_story_memory_schema()
    await ensure_story_memory_schema()
    assert await StorySubject.filter(id=subject.id, name='world').exists()
    assert await StoryCommit.filter(id=commit.id, status='accepted').exists()
    assert await StorySnapshot.filter(commit_id=commit.id).exists()
    assert await Novel.filter(id=project.id, story_outline='old outline', project_setting='old setting').exists()
    assert await Chapter.filter(id=chapter.id, content='old source', screenplay='old script').exists()
    await Tortoise.close_connections()
asyncio.run(run())
'''
    result = subprocess.run([sys.executable, '-c', script], env={**os.environ,
        'DATABASE_URL': f'sqlite://{tmp_path / "legacy.db"}', 'AUTH_ENABLED': 'false'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_postgres_story_schema_is_safe_and_uses_backend_foreign_keys(monkeypatch):
    from services.schema_compat import ensure_story_memory_schema
    from models.story_memory import StorySubject, StoryCommit, StoryFact, StorySnapshot
    from tortoise.backends.asyncpg.schema_generator import AsyncpgSchemaGenerator
    connection = Mock()
    connection.capabilities.dialect = 'postgres'
    generator = AsyncpgSchemaGenerator(connection)
    connection.schema_generator.return_value = generator
    sql = []
    async def capture(statement):
        sql.append(statement)
    connection.execute_script = capture
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: connection)
    await ensure_story_memory_schema()
    await ensure_story_memory_schema()
    assert len(sql) == 8
    assert all('CREATE TABLE IF NOT EXISTS' in statement for statement in sql)
    assert not re.search(r'^\s*(DROP|UPDATE|DELETE|ALTER)\b', '\n'.join(sql), re.MULTILINE)
    assert 'UUID' in sql[1] and 'JSONB' in sql[1]
    assert all(model._meta.db_table in '\n'.join(sql) for model in (StorySubject, StoryCommit, StoryFact, StorySnapshot))
