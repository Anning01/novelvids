"""轻量数据库兼容更新，用于没有迁移框架的已有安装。"""

from tortoise import Tortoise

from config import settings


async def ensure_resource_library_schema() -> None:
    from models.resource_library import ResourcePlacement
    connection = Tortoise.get_connection('default')
    if settings.DATABASE_URL.startswith('sqlite'):
        columns = await connection.execute_query_dict('PRAGMA table_info(video_resources)')
        if columns and 'kind' not in {row['name'] for row in columns}:
            await connection.execute_script("ALTER TABLE video_resources ADD COLUMN kind VARCHAR(24) NOT NULL DEFAULT 'video';")
        columns = await connection.execute_query_dict('PRAGMA table_info(resource_placements)')
        if columns and 'media_resource_id' not in {row['name'] for row in columns}:
            await connection.execute_script('ALTER TABLE resource_placements ADD COLUMN media_resource_id INT;')
    else:
        await connection.execute_script("ALTER TABLE IF EXISTS video_resources ADD COLUMN IF NOT EXISTS kind VARCHAR(24) NOT NULL DEFAULT 'video';")
        await connection.execute_script('ALTER TABLE IF EXISTS resource_placements ADD COLUMN IF NOT EXISTS media_resource_id INT;')
    generator = connection.schema_generator(connection)
    await connection.execute_script(generator._get_table_sql(ResourcePlacement, safe=True)['table_creation_string'])


async def ensure_video_editor_schema() -> None:
    from models.video_edit import ChapterEditDraft, EditorAsset
    from models.finished_episode import FinishedEpisodePublication
    from models.portfolio import PortfolioEpisode, PortfolioWork
    from models.resource_library import ProjectResource
    connection = Tortoise.get_connection('default')
    generator = connection.schema_generator(connection)
    for model in (ChapterEditDraft, EditorAsset, ProjectResource, FinishedEpisodePublication, PortfolioWork, PortfolioEpisode):
        definition = generator._get_table_sql(model, safe=True)
        await connection.execute_script(definition['table_creation_string'])


async def ensure_creation_agent_schema() -> None:
    """Add the opt-in tool capability before safe schema generation on old installs."""
    connection = Tortoise.get_connection("default")
    if settings.DATABASE_URL.startswith("sqlite"):
        columns = await connection.execute_query_dict("PRAGMA table_info(ai_model_configs)")
        if columns and "supports_tool_calls" not in {str(column["name"]) for column in columns}:
            await connection.execute_script(
                "ALTER TABLE ai_model_configs ADD COLUMN supports_tool_calls INT NOT NULL DEFAULT 0;"
            )
        if columns and "processing_options" not in {str(column["name"]) for column in columns}:
            await connection.execute_script("ALTER TABLE ai_model_configs ADD COLUMN processing_options JSON;")
        export_columns = await connection.execute_query_dict('PRAGMA table_info(chapter_exports)')
        if export_columns and 'source_video_id' not in {str(column['name']) for column in export_columns}:
            await connection.execute_script('ALTER TABLE chapter_exports ADD COLUMN source_video_id INT;')
    elif settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        await connection.execute_script(
            "ALTER TABLE IF EXISTS ai_model_configs ADD COLUMN IF NOT EXISTS supports_tool_calls BOOL NOT NULL DEFAULT FALSE;"
            "ALTER TABLE IF EXISTS ai_model_configs ADD COLUMN IF NOT EXISTS processing_options JSONB;"
            "ALTER TABLE IF EXISTS chapter_exports ADD COLUMN IF NOT EXISTS source_video_id INT;"
        )

    # Run before safe schema creation: it does not add columns to old tables.
    # Names below are application constants, never supplied by a request.
    for table in ("novels", "assets", "asset_variants", "scenes", "creation_agent_conversations"):
        if settings.DATABASE_URL.startswith("sqlite"):
            columns = await connection.execute_query_dict(f"PRAGMA table_info({table})")
            if columns and "deleted_at" not in {str(column["name"]) for column in columns}:
                await connection.execute_script(f"ALTER TABLE {table} ADD COLUMN deleted_at TIMESTAMP;")
        elif settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
            await connection.execute_script(
                f"ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;"
            )


async def ensure_agent_operation_schema() -> None:
    """Add durable receipts on existing installs even when automatic schemas are off."""
    from models.agent_operation import AgentOperation
    from models.agent_submission import AgentSubmission
    from models.chapter_export import ChapterExport

    connection = Tortoise.get_connection("default")
    # Reuse the ORM's backend-specific FK/UUID definitions instead of parallel DDL.
    generator = connection.schema_generator(connection)
    for model in (AgentOperation, AgentSubmission, ChapterExport):
        definition = generator._get_table_sql(model, safe=True)
        await connection.execute_script(definition["table_creation_string"])
    if settings.DATABASE_URL.startswith('sqlite'):
        columns = {row['name'] for row in await connection.execute_query_dict('PRAGMA table_info(chapter_exports)')}
        for name, field in {'collection_owner':'CHAR(36)', 'collection_lease_until':'TIMESTAMP', 'submission_slot':'INT NOT NULL DEFAULT 0', 'source_video_id':'INT'}.items():
            if name not in columns:
                await connection.execute_script(f'ALTER TABLE chapter_exports ADD COLUMN {name} {field};')
    else:
        await connection.execute_script('ALTER TABLE chapter_exports ADD COLUMN IF NOT EXISTS collection_owner UUID;'
            'ALTER TABLE chapter_exports ADD COLUMN IF NOT EXISTS collection_lease_until TIMESTAMPTZ;'
            'ALTER TABLE chapter_exports ADD COLUMN IF NOT EXISTS submission_slot BOOL NOT NULL DEFAULT FALSE;'
            'ALTER TABLE chapter_exports ADD COLUMN IF NOT EXISTS source_video_id INT;')


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
    if settings.DATABASE_URL.startswith(('postgres://', 'postgresql://')):
        await Tortoise.get_connection('default').execute_script(
            'ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS video_generation_defaults JSONB;'
            'ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS episodes_managed BOOLEAN NOT NULL DEFAULT FALSE;'
            'ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS audiovisual_guidance TEXT;'
            'ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS shot_duration_max INT NOT NULL DEFAULT 15;'
            'ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS storyboard_enabled BOOLEAN NOT NULL DEFAULT FALSE;')
        return
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
        "episodes_managed": "BOOL NOT NULL DEFAULT 0",
        "audiovisual_guidance": "TEXT",
        "shot_duration_max": "INT NOT NULL DEFAULT 15",
        "storyboard_enabled": "BOOL NOT NULL DEFAULT 0",
        "project_type": "VARCHAR(120)",
        "project_setting": "TEXT",
        "storyboard_strategy": "VARCHAR(120)",
        "storyboard_setting": "TEXT",
        "style_key": "VARCHAR(64)",
        "video_model_config_id": "INT",
        "video_generation_defaults": "JSON",
        "narrator_audio_reference_id": "INT",
    }
    statements = [
        f"ALTER TABLE novels ADD COLUMN {name} {definition};"
        for name, definition in definitions.items()
        if name not in existing
    ]
    if statements:
        await connection.execute_script("".join(statements))


async def ensure_remake_schema(*, include_indexes: bool = True) -> None:
    """补齐重制项目共享字段；只做增量操作且允许重复启动。"""
    connection = Tortoise.get_connection("default")
    if settings.DATABASE_URL.startswith("sqlite"):
        novel_columns = await connection.execute_query_dict("PRAGMA table_info(novels)")
        task_columns = await connection.execute_query_dict("PRAGMA table_info(ai_tasks)")
        if not novel_columns or not task_columns:
            return

        novel_existing = {str(column["name"]) for column in novel_columns}
        task_existing = {str(column["name"]) for column in task_columns}
        statements: list[str] = []
        novel_definitions = {
            "workflow_kind": "VARCHAR(32) NOT NULL DEFAULT 'script'",
            "aspect_ratio": "VARCHAR(16)",
            "resolution": "VARCHAR(32)",
            "custom_style_prompt": "TEXT",
            "creation_idempotency_key": "VARCHAR(64)",
            "creation_payload_hash": "VARCHAR(64)",
        }
        for name, definition in novel_definitions.items():
            if name not in novel_existing:
                statements.append(f"ALTER TABLE novels ADD COLUMN {name} {definition};")
        task_definitions = {
            "stage": "VARCHAR(32)",
            "progress": "INT NOT NULL DEFAULT 0",
        }
        for name, definition in task_definitions.items():
            if name not in task_existing:
                statements.append(f"ALTER TABLE ai_tasks ADD COLUMN {name} {definition};")
        if include_indexes and "workflow_kind" not in novel_existing:
            statements.append(
                "CREATE INDEX IF NOT EXISTS idx_novels_workflow_kind "
                "ON novels(workflow_kind);"
            )
        if include_indexes and "creation_idempotency_key" not in novel_existing:
            statements.append(
                "CREATE UNIQUE INDEX IF NOT EXISTS uid_novels_creation_idempotency_key "
                "ON novels(creation_idempotency_key);"
            )
        if statements:
            await connection.execute_script("".join(statements))
        return

    if settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        statements = [
            "ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS workflow_kind VARCHAR(32) NOT NULL DEFAULT 'script';",
            "ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS aspect_ratio VARCHAR(16);",
            "ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS resolution VARCHAR(32);",
            "ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS custom_style_prompt TEXT;",
            "ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS creation_idempotency_key VARCHAR(64);",
            "ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS creation_payload_hash VARCHAR(64);",
            "ALTER TABLE IF EXISTS ai_tasks ADD COLUMN IF NOT EXISTS stage VARCHAR(32);",
            "ALTER TABLE IF EXISTS ai_tasks ADD COLUMN IF NOT EXISTS progress INT NOT NULL DEFAULT 0;",
        ]
        if include_indexes:
            statements.append(
                "DO $$ BEGIN "
                "IF to_regclass('novels') IS NOT NULL THEN "
                "CREATE INDEX IF NOT EXISTS idx_novels_workflow_kind ON novels(workflow_kind);"
                "CREATE UNIQUE INDEX IF NOT EXISTS uid_novels_creation_idempotency_key "
                "ON novels(creation_idempotency_key);"
                "END IF; END $$;"
            )
        await connection.execute_script("".join(statements))


async def ensure_voice_reference_schema(*, include_indexes: bool = True) -> None:
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
            if include_indexes and "source" not in existing:
                statements.append(
                    "CREATE INDEX IF NOT EXISTS idx_audio_references_source "
                    "ON audio_references(source);"
                )
            if include_indexes and "team_id" not in existing:
                statements.append(
                    "CREATE INDEX IF NOT EXISTS idx_audio_references_team_id "
                    "ON audio_references(team_id);"
                )
            if statements:
                await connection.execute_script("".join(statements))
        return
    if settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        statements = [
            "ALTER TABLE IF EXISTS novels ADD COLUMN IF NOT EXISTS narrator_audio_reference_id INT;",
            "ALTER TABLE IF EXISTS audio_references ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'system';",
            "ALTER TABLE IF EXISTS audio_references ADD COLUMN IF NOT EXISTS duration DOUBLE PRECISION;",
            "ALTER TABLE IF EXISTS audio_references ADD COLUMN IF NOT EXISTS team_id INT;",
            "ALTER TABLE IF EXISTS audio_references ADD COLUMN IF NOT EXISTS created_by INT;",
        ]
        if include_indexes:
            statements.append(
                "DO $$ BEGIN "
                "IF to_regclass('audio_references') IS NOT NULL THEN "
                "CREATE INDEX IF NOT EXISTS idx_audio_references_source "
                "ON audio_references(source);"
                "CREATE INDEX IF NOT EXISTS idx_audio_references_team_id "
                "ON audio_references(team_id);"
                "END IF; END $$;"
            )
        await connection.execute_script("".join(statements))


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
    connection = Tortoise.get_connection("default")
    if settings.DATABASE_URL.startswith("sqlite"):
        await ensure_shared_team_columns()
        await _ensure_team_member_schema(connection)
        await _backfill_default_team(connection)

    from auth.models import PlatformApiKey, PlatformCallReceipt, PlatformVideoJob, QilingIdentity, QilingLoginAttempt, StudioKeyGrant, StudioMediaLease
    generator = connection.schema_generator(connection)
    for model in (QilingIdentity, QilingLoginAttempt, PlatformApiKey, PlatformCallReceipt, StudioKeyGrant, StudioMediaLease, PlatformVideoJob):
        await connection.execute_script(generator._get_table_sql(model, safe=True)['table_creation_string'])
    await _ensure_qiling_issuer_columns(connection)


async def _ensure_qiling_issuer_columns(connection) -> None:
    # An older development schema did not record the issuer. An empty value
    # keeps old attempts and identities from being trusted under a new issuer.
    for table in ("qiling_identities", "qiling_login_attempts"):
        if settings.DATABASE_URL.startswith("sqlite"):
            columns = await connection.execute_query_dict(f"PRAGMA table_info({table})")
            if columns and "issuer" not in {column["name"] for column in columns}:
                await connection.execute_script(f"ALTER TABLE {table} ADD COLUMN issuer VARCHAR(255) NOT NULL DEFAULT '';")
        elif settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
            await connection.execute_script(
                f"ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS issuer VARCHAR(255) NOT NULL DEFAULT '';"
            )


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

    # 历史个人团队（有 owner_user_id 且未设上限）回填默认人员上限 3 人
    await connection.execute_script(
        "UPDATE teams SET member_limit = 3 WHERE member_limit IS NULL AND owner_user_id IS NOT NULL;"
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
    """Only legacy projects without a team or creator belong in the default team."""
    from auth.models import Team
    from models.novel import Novel

    legacy_projects = Novel.filter(team_id=None, created_by=None)
    orphan_novels = await legacy_projects.count()
    if orphan_novels == 0:
        return
    if not await Team.exists():
        await Team.create(name="默认团队")
    default_team = await Team.first()
    await legacy_projects.update(team_id=default_team.id)
    await connection.execute_script(
        "UPDATE model_usage_records SET team_id = "
        "(SELECT team_id FROM novels WHERE novels.id = model_usage_records.novel_id) "
        "WHERE team_id IS NULL AND novel_id IN (SELECT id FROM novels);"
    )


async def ensure_recharge_order_schema() -> None:
    """确保充值订单表存在，并补充退款字段。"""
    if not settings.AUTH_ENABLED:
        return
    from auth.models import RechargeOrder
    connection = Tortoise.get_connection("default")
    generator = connection.schema_generator(connection)
    definition = generator._get_table_sql(RechargeOrder, safe=True)
    await connection.execute_script(definition["table_creation_string"])

    await ensure_recharge_refund_columns()


async def ensure_recharge_refund_columns() -> None:
    if not settings.AUTH_ENABLED:
        return
    connection = Tortoise.get_connection("default")
    if settings.DATABASE_URL.startswith("sqlite"):
        columns = await connection.execute_query_dict("PRAGMA table_info(recharge_orders)")
        if not columns:
            return
        col_names = {row["name"] for row in columns}
        if "refund_id" not in col_names:
            await connection.execute_script("ALTER TABLE recharge_orders ADD COLUMN refund_id VARCHAR(128);")
        if "refunded_at" not in col_names:
            await connection.execute_script("ALTER TABLE recharge_orders ADD COLUMN refunded_at TIMESTAMP;")
        if "refund_reason" not in col_names:
            await connection.execute_script("ALTER TABLE recharge_orders ADD COLUMN refund_reason VARCHAR(255) DEFAULT '';")
    elif settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        await connection.execute_script(
            "ALTER TABLE IF EXISTS recharge_orders ADD COLUMN IF NOT EXISTS refund_id VARCHAR(128);"
            "ALTER TABLE IF EXISTS recharge_orders ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMP WITH TIME ZONE;"
            "ALTER TABLE IF EXISTS recharge_orders ADD COLUMN IF NOT EXISTS refund_reason VARCHAR(255) DEFAULT '';"
        )


async def ensure_chapter_screenplay_schema() -> None:
    """Keep original chapter text independent from adaptations in previous releases."""
    from tortoise.transactions import in_transaction
    from models.chapter import Chapter
    from models.creation_agent import PromptChange

    async with in_transaction() as db:
        if db.capabilities.dialect == "sqlite":
            columns = await db.execute_query_dict("PRAGMA table_info(chapters)")
            if not columns or any(row["name"] == "screenplay" for row in columns):
                return
            tables = {row["name"] for row in await db.execute_query_dict(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        else:
            columns = await db.execute_query_dict(
                "SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='chapters'")
            if not columns or any(row["name"] == "screenplay" for row in columns):
                return
            await db.execute_query("LOCK TABLE chapters IN ACCESS EXCLUSIVE MODE")
            if await db.execute_query_dict("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='chapters' AND column_name='screenplay'"):
                return
            tables = {row["name"] for row in await db.execute_query_dict(
                "SELECT table_name AS name FROM information_schema.tables WHERE table_schema=current_schema()")}
        await db.execute_query("ALTER TABLE chapters ADD COLUMN screenplay TEXT")
        if "work_sync_objects" in tables:
            await db.execute_query(
                "UPDATE chapters SET screenplay=content, content='' WHERE EXISTS (SELECT 1 FROM work_sync_objects w "
                "WHERE w.kind='episode' AND w.local_id=chapters.id)")
        if "creation_prompt_changes" in tables:
            # Only classify an old adaptation when its write receipt matches the current text.
            history = {}
            for changes in await PromptChange.filter(reverted_at=None).using_db(db).order_by("id").values_list("changes", flat=True):
                for change in changes:
                    if change.get("kind") == "chapter" and "content" in change.get("after", {}):
                        chapter_id = change["target_id"]
                        before = change["before"]["content"]
                        original, previous = history.get(chapter_id, (before, before))
                        history[chapter_id] = (original if previous == before else before, change["after"]["content"])
            for chapter_id, (original, draft) in history.items():
                await Chapter.filter(id=chapter_id, screenplay=None, content=draft).using_db(db).update(
                    content=original, screenplay=draft)
