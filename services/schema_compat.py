"""轻量数据库兼容更新，用于没有迁移框架的已有安装。"""

from tortoise import Tortoise

from config import settings


async def ensure_ai_model_config_schema() -> None:
    """为已有 SQLite 数据库补齐模型能力与协议字段。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    connection = Tortoise.get_connection("default")
    columns = await connection.execute_query_dict("PRAGMA table_info(ai_model_configs)")
    if not columns:
        return

    existing = {str(column["name"]) for column in columns}
    statements = []
    if "supports_json_output" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs "
            "ADD COLUMN supports_json_output INT NOT NULL DEFAULT 0;"
        )
    if "task_types" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs "
            "ADD COLUMN task_types JSON NOT NULL DEFAULT '[]';"
            "UPDATE ai_model_configs "
            "SET task_types = '[' || task_type || ']' "
            "WHERE task_types = '[]';"
        )
    if "api_protocol" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs "
            "ADD COLUMN api_protocol VARCHAR(40) NOT NULL "
            "DEFAULT 'openai_compatible';"
        )
    if "max_context_characters" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs "
            "ADD COLUMN max_context_characters INT;"
        )
    if "image_model_type" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs "
            "ADD COLUMN image_model_type VARCHAR(40);"
        )
    if "video_model_type" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs "
            "ADD COLUMN video_model_type VARCHAR(40);"
        )
    if "pricing" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs ADD COLUMN pricing JSON;"
        )
    if statements:
        await connection.execute_script("".join(statements))


async def ensure_usage_record_schema() -> None:
    """为已有 SQLite 数据库补齐计费流水的时长字段。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    connection = Tortoise.get_connection("default")
    columns = await connection.execute_query_dict("PRAGMA table_info(model_usage_records)")
    if not columns:
        return

    existing = {str(column["name"]) for column in columns}
    if "duration_seconds" not in existing:
        await connection.execute_script(
            "ALTER TABLE model_usage_records ADD COLUMN duration_seconds REAL;"
        )


async def ensure_novel_analysis_schema() -> None:
    """为已有 SQLite 项目补齐可人工编辑的分析字段。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    connection = Tortoise.get_connection("default")
    columns = await connection.execute_query_dict("PRAGMA table_info(novels)")
    if not columns:
        return

    existing = {str(column["name"]) for column in columns}
    definitions = {
        "tags": "JSON",
        "story_outline": "TEXT",
        "project_type": "VARCHAR(120)",
        "project_setting": "TEXT",
        "storyboard_strategy": "VARCHAR(120)",
        "storyboard_setting": "TEXT",
    }
    statements = [
        f"ALTER TABLE novels ADD COLUMN {name} {definition};"
        for name, definition in definitions.items()
        if name not in existing
    ]
    if statements:
        await connection.execute_script("".join(statements))
