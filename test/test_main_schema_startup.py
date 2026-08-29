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
    assert names[:4] == [
        "init",
        "ensure_remake_schema",
        "ensure_voice_reference_schema",
        "generate",
    ]
    assert events[1][1] == {"include_indexes": False}
    assert events[2][1] == {"include_indexes": False}
