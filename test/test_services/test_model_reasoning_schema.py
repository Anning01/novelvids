import os
import sqlite3
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest


def test_reasoning_upgrade_is_additive_and_repeatable(tmp_path):
    path = tmp_path / 'old-models.db'
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE ai_model_configs (id INTEGER PRIMARY KEY, thinking VARCHAR(16)); INSERT INTO ai_model_configs VALUES (1, 'enabled');")
    code = '''
import asyncio, os
from tortoise import Tortoise
from services.schema_compat import ensure_model_reasoning_schema
async def run():
    await Tortoise.init(db_url=os.environ['DATABASE_URL'], modules={'models':['models.config']})
    await ensure_model_reasoning_schema()
    await ensure_model_reasoning_schema()
    await Tortoise.close_connections()
asyncio.run(run())
'''
    subprocess.run([sys.executable, '-c', code], check=True, env={**os.environ, 'DATABASE_URL': f'sqlite://{path}'})
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT thinking, reasoning_effort FROM ai_model_configs').fetchall() == [('enabled', None)]


@pytest.mark.asyncio
async def test_postgres_only_widens_old_thinking_column(monkeypatch):
    from services.schema_compat import ensure_model_reasoning_schema
    connection = Mock()
    connection.capabilities.dialect = 'postgres'
    connection.execute_script = AsyncMock()
    connection.execute_query_dict = AsyncMock(side_effect=[
        [{'character_maximum_length':16}], [{'character_maximum_length':64}], [{'character_maximum_length':128}], [{'character_maximum_length':None}], []])
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: connection)
    for _ in range(5):
        await ensure_model_reasoning_schema()
    statements = [call.args[0] for call in connection.execute_script.await_args_list]
    assert sum('ALTER COLUMN thinking TYPE VARCHAR(64)' in sql for sql in statements) == 1
    assert all('DROP' not in sql and 'DELETE' not in sql for sql in statements)
