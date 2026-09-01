import sqlite3
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.create_demo_snapshot import (
    _generate_video_posters,
    _rewrite_remote_references,
    create_snapshot,
)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE novels (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, cover TEXT, team_id INT,
  created_by INT, video_model_config_id INT, narrator_audio_reference_id INT,
  creation_idempotency_key TEXT, creation_payload_hash TEXT
);
CREATE TABLE chapters (
  id INTEGER PRIMARY KEY, novel_id INT REFERENCES novels(id) ON DELETE CASCADE
);
CREATE TABLE assets (
  id INTEGER PRIMARY KEY, novel_id INT REFERENCES novels(id) ON DELETE CASCADE,
  main_image TEXT, metadata JSON
);
CREATE TABLE users (
  id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT, username TEXT,
  password_hash TEXT, nickname TEXT, avatar_url TEXT, unionid TEXT, openid TEXT,
  is_super_admin INT, status INT
);
CREATE TABLE teams (
  id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT, name TEXT,
  balance NUMERIC, model_config_source TEXT, status INT, member_limit INT,
  owner_user_id INT
);
CREATE TABLE team_members (
  id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT, role TEXT, status INT,
  total_cost NUMERIC, cost_limit NUMERIC, team_id INT, user_id INT
);
CREATE TABLE ai_tasks (id TEXT PRIMARY KEY);
CREATE TABLE ai_model_configs (id INTEGER PRIMARY KEY, api_key TEXT);
CREATE TABLE user_sessions (id INTEGER PRIMARY KEY);
CREATE TABLE team_invites (id INTEGER PRIMARY KEY);
CREATE TABLE model_usage_records (id INTEGER PRIMARY KEY);
CREATE TABLE balance_transactions (id INTEGER PRIMARY KEY);
CREATE TABLE remake_uploads (id INTEGER PRIMARY KEY);
"""


def _source_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO novels VALUES (1,'保留','/media/assets/keep.png',9,9,3,4,'idem','hash')"
        )
        connection.execute(
            "INSERT INTO novels VALUES (2,'移除','/media/assets/drop.png',9,9,3,4,'idem2','hash2')"
        )
        connection.execute("INSERT INTO chapters VALUES (1,1)")
        connection.execute("INSERT INTO chapters VALUES (2,2)")
        connection.execute(
            "INSERT INTO assets VALUES (1,1,'/media/assets/keep.png',?)",
            ('{"api_key":"sk-secret-value-123456","label":"公开"}',),
        )
        connection.execute(
            "INSERT INTO assets VALUES (2,2,'/media/assets/drop.png','{}')"
        )
        connection.execute(
            "INSERT INTO users VALUES (9,'x','x','private','hash','n','','','','0',1)"
        )
        connection.execute(
            "INSERT INTO teams VALUES (9,'x','x','private',99,'custom',1,9,9)"
        )
        connection.execute(
            "INSERT INTO team_members VALUES (9,'x','x','admin',1,5,NULL,9,9)"
        )
        connection.execute("INSERT INTO ai_model_configs VALUES (1,'sk-private')")


def test_snapshot_keeps_only_selected_projects_and_media(tmp_path: Path):
    source_db = tmp_path / "source.db"
    source_media = tmp_path / "source-media"
    output = tmp_path / "snapshot"
    (source_media / "assets").mkdir(parents=True)
    (source_media / "assets" / "keep.png").write_bytes(b"keep")
    (source_media / "assets" / "drop.png").write_bytes(b"drop")
    _source_database(source_db)

    result = create_snapshot(
        source_db,
        source_media,
        output,
        [1],
        "demo",
        "public-demo-password",
        "演示团队",
    )

    assert result == {"projects": 1, "media_files": 1, "media_bytes": 4}
    assert (output / "media/assets/keep.png").read_bytes() == b"keep"
    assert not (output / "media/assets/drop.png").exists()
    with sqlite3.connect(output / "novelvids.db") as connection:
        assert connection.execute("SELECT id,name FROM novels").fetchall() == [(1, "保留")]
        assert connection.execute(
            "SELECT username,is_super_admin FROM users"
        ).fetchall() == [("demo", 0)]
        assert connection.execute(
            "SELECT balance FROM teams"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT role,cost_limit FROM team_members"
        ).fetchone() == ("viewer", 0)
        assert connection.execute("SELECT COUNT(*) FROM ai_model_configs").fetchone()[0] == 0
        metadata = connection.execute("SELECT metadata FROM assets").fetchone()[0]
        assert "sk-secret-value" not in metadata


def test_snapshot_generates_cover_derivatives_for_daily_restore(tmp_path: Path):
    source_db = tmp_path / "source.db"
    source_media = tmp_path / "source-media"
    output = tmp_path / "snapshot"
    (source_media / "assets").mkdir(parents=True)
    image = np.full((600, 400, 3), (30, 90, 160), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    original = encoded.tobytes()
    (source_media / "assets/keep.png").write_bytes(original)
    (source_media / "assets/drop.png").write_bytes(b"drop")
    _source_database(source_db)

    result = create_snapshot(
        source_db,
        source_media,
        output,
        [1],
        "demo",
        "public-demo-password",
        "演示团队",
    )

    thumbnail = output / "media/assets/derivatives/keep-thumbnail.webp"
    preview = output / "media/assets/derivatives/keep-preview.webp"
    assert thumbnail.is_file()
    assert preview.is_file()
    assert result["media_files"] == 3
    assert result["media_bytes"] == (
        len(original) + thumbnail.stat().st_size + preview.stat().st_size
    )


def test_snapshot_generates_video_posters_and_persists_metadata(
    tmp_path: Path,
    monkeypatch,
):
    media_root = tmp_path / "media"
    video = media_root / "videos/9.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    database = tmp_path / "snapshot.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE videos ("
            "id INTEGER PRIMARY KEY, url TEXT, metadata JSON, status INTEGER)"
        )
        connection.execute(
            "INSERT INTO videos VALUES (9, '/media/videos/9.mp4', ?, 3)",
            ('{"duration":5}',),
        )

        def write_frame(_service, _source: Path, destination: Path) -> None:
            image = np.full((720, 1280, 3), (30, 90, 160), dtype=np.uint8)
            success, encoded = cv2.imencode(".png", image)
            assert success
            destination.write_bytes(encoded.tobytes())

        monkeypatch.setattr(
            "scripts.create_demo_snapshot.VideoPosterService._extract_with_ffmpeg",
            write_frame,
        )
        generated, generated_bytes = _generate_video_posters(
            connection,
            media_root,
        )
        metadata = connection.execute(
            "SELECT metadata FROM videos WHERE id = 9"
        ).fetchone()[0]

    thumbnail = media_root / "videos/posters/9-thumbnail.webp"
    preview = media_root / "videos/posters/9-preview.webp"
    assert generated == 2
    assert generated_bytes == thumbnail.stat().st_size + preview.stat().st_size
    assert '"duration": 5' in metadata
    assert '"poster_thumbnail_url": "/media/videos/posters/9-thumbnail.webp"' in metadata
    assert '"poster_url": "/media/videos/posters/9-preview.webp"' in metadata


def test_snapshot_rejects_unknown_project(tmp_path: Path):
    source_db = tmp_path / "source.db"
    source_media = tmp_path / "media"
    _source_database(source_db)
    source_media.mkdir()

    with pytest.raises(ValueError, match="项目不存在"):
        create_snapshot(
            source_db,
            source_media,
            tmp_path / "snapshot",
            [999],
            "demo",
            "public-demo-password",
            "演示团队",
        )


def test_remote_references_are_rewritten_in_scalar_and_json_columns(tmp_path: Path):
    database = tmp_path / "rewrite.db"
    remote = "https://media.example.com/image.png?signature=sensitive"
    local = "/media/vendor/image.png"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE samples (id INTEGER PRIMARY KEY, url TEXT, metadata JSON)"
        )
        connection.execute(
            "INSERT INTO samples VALUES (1, ?, ?)",
            (remote, '{"nested":["' + remote + '"]}'),
        )
        _rewrite_remote_references(connection, {remote: local})
        url, metadata = connection.execute(
            "SELECT url,metadata FROM samples"
        ).fetchone()

    assert url == local
    assert remote not in metadata
    assert local in metadata
