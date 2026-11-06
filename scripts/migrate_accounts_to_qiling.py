"""CLI tool to migrate accounts (e.g. admin and testuser) into a target account (e.g. Qiling account).

Usage:
  # Dry-run preview:
  uv run python scripts/migrate_accounts_to_qiling.py --sources admin testuser --target "安宁🍃"

  # Apply migration:
  uv run python scripts/migrate_accounts_to_qiling.py --sources admin testuser --target "安宁🍃" --apply
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from tortoise import Tortoise

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth.models import User
from config import settings
from main import tortoise_config
from services.account_migration import get_consolidation_preview, migrate_accounts_to_target


async def resolve_user_id(identifier: str) -> int:
    """Resolve user by ID, username, or nickname."""
    if identifier.isdigit():
        user = await User.filter(id=int(identifier)).first()
        if user:
            return user.id
    user = await User.filter(username=identifier).first()
    if user:
        return user.id
    user = await User.filter(nickname=identifier).first()
    if user:
        return user.id
    # Try partial nickname match if exact match fails
    user = await User.filter(nickname__icontains=identifier).first()
    if user:
        return user.id
    raise ValueError(f"Cannot resolve user by identifier: '{identifier}'")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", nargs="+", help="Source user IDs, usernames, or nicknames (e.g. admin testuser)")
    parser.add_argument("--target", required=True, help="Target user ID, username, or nickname (e.g. 安宁🍃 or 3)")
    parser.add_argument("--keep-sources", action="store_true", help="Deactivate old accounts instead of deleting them")
    parser.add_argument("--apply", action="store_true", help="Execute the migration. If omitted, performs a dry-run preview")
    args = parser.parse_args()

    if not args.sources:
        parser.error("At least one --sources identifier is required")

    await Tortoise.init(config=tortoise_config)
    try:
        target_id = await resolve_user_id(args.target)
        source_ids = [await resolve_user_id(s) for s in args.sources]

        # Deduplicate source IDs
        source_ids = list(dict.fromkeys(source_ids))

        if not args.apply:
            preview = await get_consolidation_preview(source_ids, target_id)
            print("=== [DRY-RUN PREVIEW] Account Migration Plan ===")
            print(json.dumps(preview, indent=2, ensure_ascii=False))
            print("\nPass --apply to execute this migration.")
        else:
            result = await migrate_accounts_to_target(
                source_ids=source_ids,
                target_id=target_id,
                delete_sources=not args.keep_sources,
            )
            print("=== [SUCCESS] Migration Applied Successfully ===")
            print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
