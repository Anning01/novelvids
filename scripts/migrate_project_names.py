"""Preview by default. Apply only after reviewing docs/project-name-scoping.md."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from services.project_name_migration import migrate_postgres_project_names, migrate_sqlite_project_names


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path, help='Required new backup path when applying a SQLite migration')
    args = parser.parse_args()
    if settings.DATABASE_URL.startswith('sqlite://'):
        path = Path(settings.DATABASE_URL.removeprefix('sqlite://')).resolve()
        with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as connection:
            report = migrate_sqlite_project_names(connection)
            if args.apply and report['migration_required']:
                if not args.backup:
                    parser.error('--backup is required; stop the backend before applying')
                # Exclusive creation protects an existing recovery point; backup includes committed WAL data.
                descriptor = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
                with sqlite3.connect(args.backup) as backup:
                    connection.backup(backup)
        if args.apply:
            with sqlite3.connect(path) as connection:
                report = migrate_sqlite_project_names(connection, apply=True)
    elif settings.DATABASE_URL.startswith(('postgres://', 'postgresql://')):
        from tortoise import Tortoise
        from tortoise.transactions import in_transaction
        await Tortoise.init(db_url=settings.DATABASE_URL, modules={'models': []})
        try:
            async with in_transaction() as connection:
                report = await migrate_postgres_project_names(connection, apply=args.apply)
        finally:
            await Tortoise.close_connections()
    else:
        parser.error('Only SQLite and PostgreSQL are supported')
    print(json.dumps(report))


if __name__ == '__main__':
    asyncio.run(main())
