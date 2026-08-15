"""回填模型官方定价到 AiModelConfig.pricing（一次性脚本）。

用法:
    uv run python scripts/seed_model_pricing.py

幂等：重复执行会覆盖现有定价。
"""

import asyncio

from tortoise import Tortoise

from main import tortoise_config
from models.config import AiModelConfig
from services.billing.catalog import pricing_for


async def run() -> None:
    await Tortoise.init(config=tortoise_config)
    await Tortoise.generate_schemas(safe=True)
    try:
        configs = await AiModelConfig.all()
        updated = 0
        for config in configs:
            pricing = pricing_for(config)
            if pricing is None:
                print(f"  跳过（无官方定价）：{config.name} ({config.model})")
                continue
            config.pricing = pricing
            await config.save(update_fields=["pricing", "updated_at"])
            updated += 1
            print(f"  已写入：{config.name} -> {pricing}")
        print(f"完成：更新 {updated} / {len(configs)} 个模型配置")
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(run())
