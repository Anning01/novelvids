"""Explicit, reviewable migration from global project names to ownership-scoped names."""

import re
import sqlite3

from models._project_name_index import ProjectNameIndex


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def migrate_sqlite_project_names(connection: sqlite3.Connection, *, apply: bool = False) -> dict:
    table = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='novels'").fetchone()
    if not table:
        return {"migration_required": False, "project_count": 0}
    indexes = connection.execute('PRAGMA index_list("novels")').fetchall()
    global_names = [
        row for row in indexes if row[2] and not row[4]
        and [column[2] for column in connection.execute(f'PRAGMA index_info({_quoted(row[1])})')] == ["name"]
    ]
    project_count = connection.execute('SELECT COUNT(*) FROM novels').fetchone()[0]
    report = {"migration_required": bool(global_names), "project_count": project_count}
    if not apply:
        return report
    if connection.in_transaction:
        raise RuntimeError("Project name migration must run outside an active transaction")
    columns = [row[1] for row in connection.execute('PRAGMA table_info("novels")')]
    if not {"team_id", "created_by"} <= set(columns):
        raise RuntimeError("Run the existing team-column compatibility update before migrating project names")

    foreign_keys = connection.execute('PRAGMA foreign_keys').fetchone()[0]
    legacy_alter = connection.execute('PRAGMA legacy_alter_table').fetchone()[0]
    connection.execute('PRAGMA foreign_keys=OFF')
    connection.execute('PRAGMA legacy_alter_table=ON')
    try:
        connection.execute('BEGIN IMMEDIATE')
        violations = set(connection.execute('PRAGMA foreign_key_check').fetchall())
        if any(row[3] == "u" for row in global_names):
            # Preserve the original DDL, extra columns, other constraints, indexes and triggers.
            ddl, replacements = re.subn(
                r'("name"\s+VARCHAR\(\d+\)(?:\s+NOT\s+NULL)?)\s+UNIQUE\b',
                r'\1', table[0], count=1, flags=re.IGNORECASE,
            )
            if replacements != 1:
                raise RuntimeError("Unrecognized legacy name constraint; manual schema review is required")
            objects = connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE tbl_name='novels' "
                "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
            ).fetchall()
            has_sequence = connection.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone()
            sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='novels'").fetchone() if has_sequence else None
            temporary = '_novels_name_scope_migration'
            connection.execute(f'CREATE TABLE "{temporary}" ' + ddl[ddl.index('('):])
            fields = ', '.join(_quoted(column) for column in columns)
            connection.execute(f'INSERT INTO "{temporary}" ({fields}) SELECT {fields} FROM "novels"')
            connection.execute('DROP TABLE "novels"')
            connection.execute(f'ALTER TABLE "{temporary}" RENAME TO "novels"')
            removed = {row[1] for row in global_names}
            for name, sql in objects:
                if name not in removed:
                    connection.execute(sql)
            if sequence:
                connection.execute("UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name='novels'", (sequence[0],))
        else:
            for row in global_names:
                connection.execute(f'DROP INDEX {_quoted(row[1])}')
        connection.execute(ProjectNameIndex().get_sql(None, None, safe=True))
        if connection.execute('SELECT COUNT(*) FROM novels').fetchone()[0] != project_count:
            raise RuntimeError("Project count changed during migration")
        if set(connection.execute('PRAGMA foreign_key_check').fetchall()) - violations:
            raise RuntimeError("Project name migration introduced foreign key violations")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute(f'PRAGMA legacy_alter_table={legacy_alter}')
        connection.execute(f'PRAGMA foreign_keys={foreign_keys}')
    return {**report, "migration_required": False}


async def migrate_postgres_project_names(connection, *, apply: bool = False) -> dict:
    # Catalog metadata supplies the actual constraint names; never guess generated hashes.
    constraints = await connection.execute_query_dict(
        "SELECT c.conname FROM pg_constraint c JOIN pg_attribute a "
        "ON a.attrelid=c.conrelid AND a.attname='name' "
        "WHERE c.conrelid=to_regclass('novels') AND c.contype='u' "
        "AND c.conkey=ARRAY[a.attnum]"
    )
    indexes = await connection.execute_query_dict(
        "SELECT ci.relname AS index_name FROM pg_index i "
        "JOIN pg_class ci ON ci.oid=i.indexrelid "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attname='name' "
        "WHERE i.indrelid=to_regclass('novels') AND i.indisunique "
        "AND i.indnkeyatts=1 AND i.indkey[0]=a.attnum AND i.indpred IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid=i.indexrelid)"
    )
    report = {"migration_required": bool(constraints or indexes)}
    if not apply:
        return report
    # The caller holds a transaction; installing the replacement precedes removing the old guard.
    await connection.execute_query(ProjectNameIndex().get_sql(None, None, safe=True))
    for row in constraints:
        await connection.execute_query(f'ALTER TABLE "novels" DROP CONSTRAINT {_quoted(row["conname"])}')
    for row in indexes:
        await connection.execute_query(f'DROP INDEX {_quoted(row["index_name"])}')
    return {"migration_required": False}
