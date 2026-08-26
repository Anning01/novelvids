from unittest.mock import AsyncMock

import pytest

from services.schema_compat import (
    ensure_ai_model_config_schema,
    ensure_novel_analysis_schema,
    ensure_voice_reference_schema,
)


@pytest.mark.asyncio
async def test_ai_model_config_schema_adds_protocol_once_across_repeated_startups(
    monkeypatch,
):
    connection = AsyncMock()
    connection.execute_query_dict.side_effect = [
        [
            {"name": "supports_json_output"},
            {"name": "task_types"},
        ],
        [
            {"name": "supports_json_output"},
            {"name": "task_types"},
            {"name": "api_protocol"},
            {"name": "max_context_characters"},
            {"name": "image_model_type"},
            {"name": "video_model_type"},
            {"name": "pricing"},
            {"name": "thinking"},
            {"name": "max_tokens"},
        ],
    ]
    monkeypatch.setattr(
        "services.schema_compat.Tortoise.get_connection",
        lambda _: connection,
    )
    monkeypatch.setattr(
        "services.schema_compat.settings.DATABASE_URL",
        "sqlite://compat-test.db",
    )

    await ensure_ai_model_config_schema()
    await ensure_ai_model_config_schema()

    connection.execute_script.assert_awaited_once()
    script = connection.execute_script.await_args.args[0]
    assert "ADD COLUMN api_protocol" in script
    assert "DEFAULT 'openai_compatible'" in script
    assert "ADD COLUMN max_context_characters INT" in script
    assert "ADD COLUMN image_model_type VARCHAR(40)" in script
    assert "ADD COLUMN video_model_type VARCHAR(40)" in script
    assert "ADD COLUMN pricing JSON" in script
    assert "ADD COLUMN thinking VARCHAR(16)" in script
    assert "ADD COLUMN max_tokens INT" in script


@pytest.mark.asyncio
async def test_novel_analysis_schema_adds_editable_fields_once_across_repeated_startups(
    monkeypatch,
):
    connection = AsyncMock()
    existing = [{"name": "id"}, {"name": "name"}]
    completed = [
        *existing,
        {"name": "tags"},
        {"name": "story_outline"},
        {"name": "project_type"},
        {"name": "project_setting"},
        {"name": "storyboard_strategy"},
        {"name": "storyboard_setting"},
        {"name": "style_key"},
        {"name": "video_model_config_id"},
        {"name": "narrator_audio_reference_id"},
    ]
    connection.execute_query_dict.side_effect = [existing, completed]
    monkeypatch.setattr(
        "services.schema_compat.Tortoise.get_connection",
        lambda _: connection,
    )
    monkeypatch.setattr(
        "services.schema_compat.settings.DATABASE_URL",
        "sqlite://compat-test.db",
    )

    await ensure_novel_analysis_schema()
    await ensure_novel_analysis_schema()

    connection.execute_script.assert_awaited_once()
    script = connection.execute_script.await_args.args[0]
    assert "ADD COLUMN tags JSON" in script
    assert "ADD COLUMN story_outline TEXT" in script
    assert "ADD COLUMN project_type VARCHAR(120)" in script
    assert "ADD COLUMN project_setting TEXT" in script
    assert "ADD COLUMN storyboard_strategy VARCHAR(120)" in script
    assert "ADD COLUMN storyboard_setting TEXT" in script
    assert "ADD COLUMN style_key VARCHAR(64)" in script
    assert "ADD COLUMN video_model_config_id INT" in script
    assert "ADD COLUMN narrator_audio_reference_id INT" in script


@pytest.mark.asyncio
async def test_voice_reference_schema_adds_audio_library_fields_once(monkeypatch):
    connection = AsyncMock()
    existing = [{"name": "id"}, {"name": "asset_id"}]
    completed = [
        *existing,
        {"name": "source"},
        {"name": "duration"},
        {"name": "team_id"},
        {"name": "created_by"},
    ]
    connection.execute_query_dict.side_effect = [existing, completed]
    monkeypatch.setattr(
        "services.schema_compat.Tortoise.get_connection",
        lambda _: connection,
    )
    monkeypatch.setattr(
        "services.schema_compat.settings.DATABASE_URL",
        "sqlite://compat-test.db",
    )

    await ensure_voice_reference_schema()
    await ensure_voice_reference_schema()

    connection.execute_script.assert_awaited_once()
    script = connection.execute_script.await_args.args[0]
    assert "ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'system'" in script
    assert "ADD COLUMN duration REAL" in script
    assert "ADD COLUMN team_id INT" in script
    assert "ADD COLUMN created_by INT" in script
