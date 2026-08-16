"""共享表团队增量列迁移的回归测试。

模拟旧库缺列场景：模型已带新字段而 SQLite 表仍是旧结构，
启动迁移必须无条件补列，否则 ORM 插入会报 no column named ...。
"""

import pytest
from tortoise import Tortoise

from models.config import AiModelConfig
from models.novel import Novel
from services.schema_compat import ensure_shared_team_columns
from utils.enums import AiTaskTypeEnum


def _columns(rows: list[dict]) -> set[str]:
    return {str(row["name"]) for row in rows}


@pytest.mark.asyncio
async def test_shared_team_columns_restore_legacy_schema():
    """旧库缺列 → ensure_shared_team_columns 补列 → ORM 插入正常。"""
    connection = Tortoise.get_connection("default")

    # 模拟旧库：删除（非索引）增量列
    await connection.execute_script("ALTER TABLE ai_model_configs DROP COLUMN scope;")
    await connection.execute_script("ALTER TABLE novels DROP COLUMN created_by;")

    assert "scope" not in _columns(
        await connection.execute_query_dict("PRAGMA table_info(ai_model_configs)")
    )
    assert "created_by" not in _columns(
        await connection.execute_query_dict("PRAGMA table_info(novels)")
    )

    # 无条件迁移（与 main.py lifespan 相同的入口）
    await ensure_shared_team_columns()

    assert "scope" in _columns(
        await connection.execute_query_dict("PRAGMA table_info(ai_model_configs)")
    )
    assert "team_id" in _columns(
        await connection.execute_query_dict("PRAGMA table_info(ai_model_configs)")
    )
    assert "created_by" in _columns(
        await connection.execute_query_dict("PRAGMA table_info(novels)")
    )

    # 复现原始故障路径：模型配置插入（种子数据同款操作）
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value],
        name="legacy-migration-check",
        base_url="https://example.com/v1",
        api_key="k",
        model="m",
        is_active=False,
    )
    assert config.scope == "official"
    assert config.team_id is None

    novel = await Novel.create(name="legacy-migration-novel", author="x")
    assert novel.team_id is None
    assert novel.created_by is None


@pytest.mark.asyncio
async def test_shared_team_columns_idempotent_on_current_schema():
    """当前新库上重复执行迁移：无副作用、不抛异常。"""
    await ensure_shared_team_columns()
    await ensure_shared_team_columns()
