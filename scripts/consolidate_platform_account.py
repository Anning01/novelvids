"""Transfer platform administrator access after the receiving account has bound Qiling."""
import argparse
import asyncio
import sys
from pathlib import Path

from tortoise import Tortoise

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth.account_consolidation import consolidate_platform_account
from config import settings
from main import tortoise_config


async def run(source: int | None, target: int) -> None:
    if not settings.AUTH_ENABLED:
        raise SystemExit("AUTH_ENABLED is required")
    await Tortoise.init(config=tortoise_config)
    try:
        await consolidate_platform_account(source, target)
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int, help="Omit only when provisioning the first platform administrator")
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Review both account IDs and create a backup before passing --apply")
    asyncio.run(run(args.source_id, args.target_id))
    print("Platform access transferred. Sign in with the receiving account.")
