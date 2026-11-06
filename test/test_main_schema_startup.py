import pytest

import main as app_main


def _record(events: list[tuple[str, dict[str, object]]], name: str):
    async def invoke(*_args, **kwargs):
        events.append((name, kwargs))

    return invoke


@pytest.mark.asyncio
async def test_legacy_columns_are_added_before_safe_schema_generation(monkeypatch):
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(app_main.settings, "GENERATE_SCHEMAS", True)
    monkeypatch.setattr(
        app_main.Tortoise,
        "init",
        _record(events, "init"),
    )
    monkeypatch.setattr(
        app_main.Tortoise,
        "generate_schemas",
        _record(events, "generate"),
    )
    for name in (
        "ensure_remake_schema",
        "ensure_voice_reference_schema",
        "ensure_ai_model_config_schema",
        "ensure_novel_analysis_schema",
        "ensure_usage_record_schema",
        "ensure_shared_team_columns",
    ):
        monkeypatch.setattr(app_main, name, _record(events, name))

    await app_main._initialize_database_schema()

    names = [name for name, _kwargs in events]
    assert names[:6] == [
        "init",
        "ensure_remake_schema",
        "ensure_voice_reference_schema",
        "ensure_shared_team_columns",
        "ensure_novel_analysis_schema",
        "generate",
    ]
    assert events[1][1] == {"include_indexes": False}
    assert events[2][1] == {"include_indexes": False}


@pytest.mark.parametrize("auth_enabled", ["false", "true"])
def test_fresh_database_boots_twice_without_losing_data_or_enabling_auth(tmp_path, auth_enabled):
    import os
    import subprocess
    import sys
    script = """
import asyncio
from tortoise import Tortoise
from main import _initialize_database_schema
from config import settings
from models.novel import Novel
async def run():
    await _initialize_database_schema()
    project = await Novel.create(name='startup-sentinel')
    project_id = project.id
    await Tortoise.close_connections()
    await _initialize_database_schema()
    assert await Novel.filter(id=project_id, name='startup-sentinel').exists()
    connection = Tortoise.get_connection('default')
    tables = {row['name'] for row in await connection.execute_query_dict("SELECT name FROM sqlite_master WHERE type='table'")}
    assert ('users' in tables) == settings.AUTH_ENABLED
    assert ('recharge_orders' in tables) == settings.AUTH_ENABLED
    await Tortoise.close_connections()
asyncio.run(run())
"""
    result = subprocess.run([sys.executable, "-c", script], env={**os.environ,
        "AUTH_ENABLED": auth_enabled, "AUTH_PROVIDER": "password",
        "DATABASE_URL": f"sqlite://{tmp_path / 'startup.db'}", "GENERATE_SCHEMAS": "true"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
