"""Safe startup compatibility for persistent local model choices."""

import os
import sqlite3
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest


def test_legacy_sqlite_keeps_states_and_choices_across_restarts(tmp_path):
    database = tmp_path / 'legacy.db'
    with sqlite3.connect(database) as connection:
        connection.executescript('''
            CREATE TABLE ai_model_configs (id INTEGER PRIMARY KEY, name TEXT, is_active INT, pricing TEXT);
            INSERT INTO ai_model_configs VALUES (1,'enabled',1,'{"price":1}'),(2,'unavailable',0,'{"price":2}');
        ''')
    script = '''
import asyncio, os
from tortoise import Tortoise
from services.schema_compat import ensure_model_local_activation_schema
async def main():
    await Tortoise.init(db_url=os.environ['DATABASE_URL'], modules={'models':['models.config']})
    await ensure_model_local_activation_schema()
    await ensure_model_local_activation_schema()
    await Tortoise.close_connections()
asyncio.run(main())
'''
    environment = {**os.environ, 'DATABASE_URL': f'sqlite://{database}'}
    subprocess.run([sys.executable, '-c', script], env=environment, check=True)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT id,is_active,local_enabled,pricing FROM ai_model_configs ORDER BY id').fetchall() == [
            (1, 1, 1, '{"price":1}'), (2, 0, 1, '{"price":2}')]
        connection.execute('UPDATE ai_model_configs SET local_enabled=0 WHERE id=1')
    subprocess.run([sys.executable, '-c', script], env=environment, check=True)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT local_enabled FROM ai_model_configs WHERE id=1').fetchone() == (0,)


@pytest.mark.asyncio
async def test_postgres_adds_choice_column_safely(monkeypatch):
    from services.schema_compat import ensure_model_local_activation_schema
    connection = Mock()
    connection.capabilities.dialect = 'postgres'
    connection.execute_script = AsyncMock()
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: connection)
    await ensure_model_local_activation_schema()
    assert connection.execute_script.await_args.args[0] == (
        'ALTER TABLE IF EXISTS ai_model_configs ADD COLUMN IF NOT EXISTS local_enabled BOOL NOT NULL DEFAULT TRUE;')
