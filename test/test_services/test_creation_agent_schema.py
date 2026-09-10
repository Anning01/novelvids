from unittest.mock import AsyncMock

import pytest

from services.schema_compat import ensure_creation_agent_schema


@pytest.mark.asyncio
async def test_tool_capability_is_opt_in_and_added_only_once(monkeypatch):
    connection = AsyncMock()
    columns = {'ai_model_configs': [{'name': 'id'}]}
    async def inspect(statement):
        table = statement.removeprefix('PRAGMA table_info(').removesuffix(')')
        return columns.get(table, [])
    async def execute(statement):
        columns['ai_model_configs'].append({'name': 'supports_tool_calls'})
    connection.execute_query_dict.side_effect = inspect
    connection.execute_script.side_effect = execute
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: connection)
    monkeypatch.setattr('services.schema_compat.settings.DATABASE_URL', 'sqlite://test.db')
    await ensure_creation_agent_schema()
    await ensure_creation_agent_schema()
    connection.execute_script.assert_awaited_once_with('ALTER TABLE ai_model_configs ADD COLUMN supports_tool_calls INT NOT NULL DEFAULT 0;')


@pytest.mark.asyncio
async def test_postgres_capability_migration_is_additive_and_idempotent(monkeypatch):
    connection = AsyncMock()
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: connection)
    monkeypatch.setattr('services.schema_compat.settings.DATABASE_URL', 'postgres://test')
    await ensure_creation_agent_schema()
    statement = connection.execute_script.await_args_list[0].args[0]
    assert 'ADD COLUMN IF NOT EXISTS supports_tool_calls' in statement
    assert 'DEFAULT FALSE' in statement
    assert 'DROP' not in statement
    assert all('ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ' in call.args[0]
               for call in connection.execute_script.await_args_list[1:])


@pytest.mark.asyncio
async def test_capability_migration_runs_before_generation(monkeypatch):
    import main
    events = []
    def record(name):
        async def run(*args, **kwargs):
            events.append(name)
        return run
    monkeypatch.setattr(main.settings, 'GENERATE_SCHEMAS', True)
    monkeypatch.setattr(main.Tortoise, 'init', record('init'))
    monkeypatch.setattr(main.Tortoise, 'generate_schemas', record('generate'))
    for name in ('ensure_creation_agent_schema', 'ensure_remake_schema', 'ensure_voice_reference_schema',
                 'ensure_ai_model_config_schema', 'ensure_novel_analysis_schema', 'ensure_usage_record_schema', 'ensure_shared_team_columns'):
        monkeypatch.setattr(main, name, record(name))
    await main._initialize_database_schema()
    assert events.index('ensure_creation_agent_schema') < events.index('generate')
