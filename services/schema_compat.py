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
    if "thinking" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs ADD COLUMN thinking VARCHAR(16);"
        )
    if "max_tokens" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs ADD COLUMN max_tokens INT;"
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
    """为已有 SQLite 项目补齐分析字段与工作台偏好。"""
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
        "style_key": "VARCHAR(64)",
        "video_model_config_id": "INT",
        "narrator_audio_reference_id": "INT",
    }
    statements = [
        f"ALTER TABLE novels ADD COLUMN {name} {definition};"
        for name, definition in definitions.items()
        if name not in existing
    ]
    if statements:
        await connection.execute_script("".join(statements))


async def ensure_voice_reference_schema() -> None:
    """Add reusable voice fields for both existing SQLite and PostgreSQL installs."""
    connection = Tortoise.get_connection("default")
    if settings.DATABASE_URL.startswith("sqlite"):
        audio_columns = await connection.execute_query_dict("PRAGMA table_info(audio_references)")
        if audio_columns:
            existing = {str(column["name"]) for column in audio_columns}
            definitions = {
                "source": "VARCHAR(16) NOT NULL DEFAULT 'system'",
                "duration": "REAL",
                "team_id": "INT",
                "created_by": "INT",
            }
            statements = [
                f"ALTER TABLE audio_references ADD COLUMN {name} {definition};"
                for name, definition in definitions.items()
                if name not in existing
            ]
            if statements:
                await connection.execute_script("".join(statements))
        return
    if settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        await connection.execute_script(
            "ALTER TABLE novels ADD COLUMN IF NOT EXISTS narrator_audio_reference_id INT;"
            "ALTER TABLE audio_references ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'system';"
            "ALTER TABLE audio_references ADD COLUMN IF NOT EXISTS duration DOUBLE PRECISION;"
            "ALTER TABLE audio_references ADD COLUMN IF NOT EXISTS team_id INT;"
            "ALTER TABLE audio_references ADD COLUMN IF NOT EXISTS created_by INT;"
            "CREATE INDEX IF NOT EXISTS idx_audio_references_source ON audio_references(source);"
            "CREATE INDEX IF NOT EXISTS idx_audio_references_team_id ON audio_references(team_id);"
        )


async def ensure_shared_team_columns() -> None:
    """无条件补齐共享表（novels / model_usage_records / ai_model_configs）的
    团队相关增量列。

    这些列在模型上始终存在（vanilla 下恒为 NULL），因此无论开关状态如何，
    旧库都必须补列，否则 ORM 插入会因缺列失败。纯增量、幂等、vanilla 无副作用。
    """
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    connection = Tortoise.get_connection("default")

    novel_columns = await connection.execute_query_dict("PRAGMA table_info(novels)")
    if novel_columns:
        existing = {str(column["name"]) for column in novel_columns}
        statements = []
        if "team_id" not in existing:
            statements.append("ALTER TABLE novels ADD COLUMN team_id INT;")
        if "created_by" not in existing:
            statements.append("ALTER TABLE novels ADD COLUMN created_by INT;")
        if statements:
            await connection.execute_script("".join(statements))

    usage_columns = await connection.execute_query_dict(
        "PRAGMA table_info(model_usage_records)"
    )
    if usage_columns:
        existing = {str(column["name"]) for column in usage_columns}
        statements = []
        if "team_id" not in existing:
            statements.append("ALTER TABLE model_usage_records ADD COLUMN team_id INT;")
        if "user_id" not in existing:
            statements.append("ALTER TABLE model_usage_records ADD COLUMN user_id INT;")
        if "cost_source" not in existing:
            statements.append(
                "ALTER TABLE model_usage_records ADD COLUMN cost_source VARCHAR(16) "
                "NOT NULL DEFAULT 'balance';"
            )
        if statements:
            await connection.execute_script("".join(statements))

    await _ensure_model_config_scope_schema(connection)


async def ensure_team_schema() -> None:
    """AUTH_ENABLED=true 时补齐团队专属表字段并回填存量数据。

    - 共享表增量列（无条件，见 ensure_shared_team_columns）
    - teams / team_members 表增量列
    - 尚无团队时创建「默认团队」，把存量小说与计费流水挂入
    """
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    connection = Tortoise.get_connection("default")
    await ensure_shared_team_columns()

    await _ensure_team_member_schema(connection)
    await _backfill_default_team(connection)


async def _ensure_team_member_schema(connection) -> None:
    """团队/成员表补充第二阶段字段并回填成员累计消耗。"""
    team_columns = await connection.execute_query_dict("PRAGMA table_info(teams)")
    if team_columns:
        existing = {str(column["name"]) for column in team_columns}
        if "member_limit" not in existing:
            await connection.execute_script(
                "ALTER TABLE teams ADD COLUMN member_limit INT;"
            )
        if "owner_user_id" not in existing:
            await connection.execute_script(
                "ALTER TABLE teams ADD COLUMN owner_user_id INT;"
            )

    # 回填团队所有人：取该团队最早的一位管理员
    await connection.execute_script(
        "UPDATE teams SET owner_user_id = COALESCE(owner_user_id, ("
        "  SELECT user_id FROM team_members "
        "  WHERE team_members.team_id = teams.id AND team_members.role = 'admin' "
        "  ORDER BY team_members.id LIMIT 1"
        ")) WHERE owner_user_id IS NULL AND EXISTS ("
        "  SELECT 1 FROM team_members WHERE team_members.team_id = teams.id"
        ");"
    )

    member_columns = await connection.execute_query_dict(
        "PRAGMA table_info(team_members)"
    )
    if member_columns:
        existing = {str(column["name"]) for column in member_columns}
        statements = []
        if "status" not in existing:
            statements.append(
                "ALTER TABLE team_members ADD COLUMN status INT NOT NULL DEFAULT 1;"
            )
        if "total_cost" not in existing:
            statements.append(
                "ALTER TABLE team_members ADD COLUMN total_cost DECIMAL(18,6) "
                "NOT NULL DEFAULT 0;"
            )
        if "cost_limit" not in existing:
            statements.append(
                "ALTER TABLE team_members ADD COLUMN cost_limit DECIMAL(18,6);"
            )
        if statements:
            await connection.execute_script("".join(statements))

    # 回填成员累计消耗：仅对可追溯到成员的历史计费流水生效
    await connection.execute_script(
        "UPDATE team_members SET total_cost = COALESCE(("
        "  SELECT SUM(cost) FROM model_usage_records "
        "  WHERE model_usage_records.team_id = team_members.team_id "
        "    AND model_usage_records.user_id = team_members.user_id"
        "), 0) WHERE total_cost = 0;"
    )


async def _ensure_model_config_scope_schema(connection) -> None:
    """为已有 SQLite 数据库的模型配置表补齐官方/团队归属字段。"""
    columns = await connection.execute_query_dict(
        "PRAGMA table_info(ai_model_configs)"
    )
    if not columns:
        return
    existing = {str(column["name"]) for column in columns}
    statements = []
    if "scope" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs ADD COLUMN scope VARCHAR(16) "
            "NOT NULL DEFAULT 'official';"
        )
    if "team_id" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs ADD COLUMN team_id INT;"
        )
    if statements:
        await connection.execute_script("".join(statements))


async def _backfill_default_team(connection) -> None:
    """尚无团队且存在无归属小说时，创建默认团队并回填 team_id。"""
    from auth.models import Team
    from models.novel import Novel

    orphan_novels = await Novel.filter(team_id=None).count()
    if orphan_novels == 0:
        return
    if not await Team.exists():
        await Team.create(name="默认团队")
    default_team = await Team.first()
    await Novel.filter(team_id=None).update(team_id=default_team.id)
    await connection.execute_script(
        "UPDATE model_usage_records SET team_id = "
        "(SELECT team_id FROM novels WHERE novels.id = model_usage_records.novel_id) "
        "WHERE team_id IS NULL AND novel_id IN (SELECT id FROM novels);"
    )
