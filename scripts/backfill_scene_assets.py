"""回填分镜资产引用到 scene.assets（一次性脚本）。

用法:
    uv run python scripts/backfill_scene_assets.py

幂等：重复执行不会产生重复关联。
"""

import asyncio

from tortoise import Tortoise

from main import tortoise_config
from services.scene_asset_backfill import backfill_scene_assets


async def run() -> None:
    await Tortoise.init(config=tortoise_config)
    await Tortoise.generate_schemas(safe=True)
    try:
        stats = await backfill_scene_assets()
        print(
            f"回填完成：扫描镜头 {stats['scenes']} 个，"
            f"更新 {stats['updated_scenes']} 个，补链资产 {stats['linked_assets']} 条"
        )
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(run())
