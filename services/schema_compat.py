"""轻量数据库兼容更新，用于没有迁移框架的已有安装。"""

from tortoise import Tortoise

from config import settings


async def ensure_ai_model_config_schema() -> None:
    """为已有 SQLite 数据库补齐模型 JSON 输出能力字段。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    connection = Tortoise.get_connection("default")
    columns = await connection.execute_query_dict("PRAGMA table_info(ai_model_configs)")
    if columns and not any(column["name"] == "supports_json_output" for column in columns):
        await connection.execute_script(
            "ALTER TABLE ai_model_configs "
            "ADD COLUMN supports_json_output INT NOT NULL DEFAULT 0;"
        )
