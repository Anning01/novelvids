import sqlite3
from unittest.mock import AsyncMock

import pytest

from models._project_name_index import ProjectNameIndex
from services.project_name_migration import migrate_postgres_project_names, migrate_sqlite_project_names


@pytest.fixture
def legacy_connection():
    connection = sqlite3.connect(':memory:', isolation_level=None)
    connection.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE novels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            "name" VARCHAR(255) NOT NULL UNIQUE,
            team_id INT, created_by INT, content TEXT, extra JSON,
            creation_idempotency_key VARCHAR(64) UNIQUE
        );
        CREATE TABLE chapters (id INTEGER PRIMARY KEY, novel_id INT REFERENCES novels(id) ON DELETE CASCADE, content TEXT);
        CREATE TABLE audit (project_id INT);
        CREATE INDEX extra_project_index ON novels(created_by);
        CREATE TRIGGER keep_project_audit AFTER UPDATE OF content ON novels BEGIN INSERT INTO audit VALUES (NEW.id); END;
        CREATE VIEW project_titles AS SELECT id, name FROM novels;
        INSERT INTO novels VALUES (1, 'Example', 7, 1, 'Original manuscript', '{"legacy":true}', 'old-key');
        INSERT INTO chapters VALUES (1, 1, 'Original chapter');
        UPDATE sqlite_sequence SET seq=500 WHERE name='novels';
    ''')
    yield connection
    connection.close()


def snapshot(connection):
    return {
        table: connection.execute(f'SELECT * FROM {table}').fetchall()
        for table in ('novels', 'chapters', 'audit', 'sqlite_sequence')
    }


def test_preview_does_not_change_schema_or_data(legacy_connection):
    before = snapshot(legacy_connection)
    ddl = legacy_connection.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall()
    report = migrate_sqlite_project_names(legacy_connection)
    assert report == {'migration_required': True, 'project_count': 1}
    assert snapshot(legacy_connection) == before
    assert legacy_connection.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall() == ddl


@pytest.mark.parametrize("legacy_alter", [0, 1])
def test_migration_preserves_data_relations_other_constraints_and_sequence(legacy_connection, legacy_alter):
    legacy_connection.execute(f"PRAGMA legacy_alter_table={legacy_alter}")
    before = snapshot(legacy_connection)
    assert migrate_sqlite_project_names(legacy_connection, apply=True)['migration_required'] is False
    assert snapshot(legacy_connection) == before
    assert legacy_connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert legacy_connection.execute('PRAGMA legacy_alter_table').fetchone()[0] == legacy_alter
    assert legacy_connection.execute('PRAGMA foreign_key_check').fetchall() == []
    assert legacy_connection.execute('SELECT * FROM project_titles').fetchall() == [(1, 'Example')]
    assert any(row[1] == 'extra_project_index' for row in legacy_connection.execute('PRAGMA index_list(novels)'))
    with pytest.raises(sqlite3.IntegrityError):
        legacy_connection.execute("INSERT INTO novels(name, creation_idempotency_key) VALUES ('Other', 'old-key')")
    legacy_connection.execute("UPDATE novels SET content='Changed manuscript' WHERE id=1")
    assert legacy_connection.execute('SELECT * FROM audit').fetchall() == [(1,)]
    cursor = legacy_connection.execute("INSERT INTO novels(name, team_id) VALUES ('Example', 8)")
    assert cursor.lastrowid == 501


def test_names_are_unique_per_team_or_person_after_migration(legacy_connection):
    migrate_sqlite_project_names(legacy_connection, apply=True)
    for team, creator in [(8, 1), (None, 1), (None, 2), (None, None)]:
        legacy_connection.execute('INSERT INTO novels(name, team_id, created_by) VALUES (?, ?, ?)', ('Example', team, creator))
    for team, creator in [(7, 2), (None, 1), (None, None)]:
        with pytest.raises(sqlite3.IntegrityError):
            legacy_connection.execute('INSERT INTO novels(name, team_id, created_by) VALUES (?, ?, ?)', ('Example', team, creator))


def test_repeated_migration_does_not_rebuild_current_table(legacy_connection):
    migrate_sqlite_project_names(legacy_connection, apply=True)
    before = snapshot(legacy_connection)
    ddl = legacy_connection.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall()
    for _ in range(2):
        assert migrate_sqlite_project_names(legacy_connection, apply=True)['migration_required'] is False
    assert snapshot(legacy_connection) == before
    assert legacy_connection.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall() == ddl


@pytest.mark.parametrize("legacy_alter", [0, 1])
def test_failure_rolls_back_schema_and_data_and_restores_foreign_keys(legacy_connection, monkeypatch, legacy_alter):
    legacy_connection.execute(f"PRAGMA legacy_alter_table={legacy_alter}")
    before = snapshot(legacy_connection)
    ddl = legacy_connection.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall()
    monkeypatch.setattr(ProjectNameIndex, 'get_sql', lambda *args, **kwargs: 'INVALID SQL')
    with pytest.raises(sqlite3.OperationalError):
        migrate_sqlite_project_names(legacy_connection, apply=True)
    assert snapshot(legacy_connection) == before
    assert legacy_connection.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall() == ddl
    assert legacy_connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert legacy_connection.execute('PRAGMA legacy_alter_table').fetchone()[0] == legacy_alter


def test_unknown_legacy_constraint_fails_without_changing_the_table():
    with sqlite3.connect(':memory:', isolation_level=None) as connection:
        connection.execute('CREATE TABLE novels (id INT, name VARCHAR(255) NOT NULL, team_id INT, created_by INT, UNIQUE(name))')
        with pytest.raises(RuntimeError, match='manual schema review'):
            migrate_sqlite_project_names(connection, apply=True)
        assert migrate_sqlite_project_names(connection)['migration_required'] is True


@pytest.mark.asyncio
async def test_cli_preview_and_apply_keep_a_restorable_backup(tmp_path, legacy_connection, monkeypatch, capsys):
    from scripts import migrate_project_names as command

    database = tmp_path / 'projects.db'
    backup = tmp_path / 'before.db'
    with sqlite3.connect(database) as destination:
        legacy_connection.backup(destination)
    monkeypatch.setattr(command.settings, 'DATABASE_URL', f'sqlite://{database}')
    monkeypatch.setattr('sys.argv', ['migrate_project_names.py'])
    await command.main()
    assert '"migration_required": true' in capsys.readouterr().out
    assert not backup.exists()
    monkeypatch.setattr('sys.argv', ['migrate_project_names.py', '--apply', '--backup', str(backup)])
    await command.main()
    with sqlite3.connect(backup) as connection:
        assert snapshot(connection) == snapshot(legacy_connection)
        assert migrate_sqlite_project_names(connection)['migration_required'] is True
    with sqlite3.connect(database) as connection:
        assert snapshot(connection) == snapshot(legacy_connection)
        assert migrate_sqlite_project_names(connection)['migration_required'] is False
    assert backup.stat().st_mode & 0o777 == 0o600
    # Already migrated: no new backup and no duplicate table rebuild on a repeated run.
    await command.main()


@pytest.mark.asyncio
async def test_cli_will_not_overwrite_an_existing_backup(tmp_path, legacy_connection, monkeypatch):
    from scripts import migrate_project_names as command

    database = tmp_path / 'projects.db'
    backup = tmp_path / 'before.db'
    with sqlite3.connect(database) as destination:
        legacy_connection.backup(destination)
    backup.write_text('existing recovery point')
    monkeypatch.setattr(command.settings, 'DATABASE_URL', f'sqlite://{database}')
    monkeypatch.setattr('sys.argv', ['migrate_project_names.py', '--apply', '--backup', str(backup)])
    with pytest.raises(FileExistsError):
        await command.main()
    assert backup.read_text() == 'existing recovery point'
    with sqlite3.connect(database) as connection:
        assert migrate_sqlite_project_names(connection)['migration_required'] is True


@pytest.mark.asyncio
async def test_postgres_preview_and_constraint_replacement_use_catalog_names():
    connection = AsyncMock()
    connection.execute_query_dict.side_effect = [
        [{'conname': 'legacy_name_key'}], [{'index_name': 'legacy_name_index'}],
        [{'conname': 'legacy_name_key'}], [{'index_name': 'legacy_name_index'}],
    ]
    assert (await migrate_postgres_project_names(connection))['migration_required'] is True
    connection.execute_query.assert_not_awaited()
    assert (await migrate_postgres_project_names(connection, apply=True))['migration_required'] is False
    statements = [call.args[0] for call in connection.execute_query.await_args_list]
    assert statements[0] == ProjectNameIndex().get_sql(None, None, safe=True)
    assert statements[1] == 'ALTER TABLE "novels" DROP CONSTRAINT "legacy_name_key"'
    assert statements[2] == 'DROP INDEX "legacy_name_index"'
