#!/usr/bin/env python3
"""从本地 SQLite 安全制作可每日恢复的只读演示快照。

脚本只接受显式项目 ID，使用 SQLite backup API 获取一致性副本，再移除账号、
会话、账单、模型配置和未选项目。媒体目录仅复制保留数据实际引用的本地文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlparse

from services.cover_derivatives import (
    local_media_path,
    render_cover_derivatives,
    write_local_cover_derivatives,
)
from services.video.poster import VideoPosterService, video_poster_reference
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
)
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:sk|ak|secret|token)[-_][a-z0-9_-]{12,}"
)
MEDIA_PREFIXES = ("/media/", "./media/", "media/")
CONTENT_TYPE_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
ALLOWED_MEDIA_EXTENSIONS = set(CONTENT_TYPE_EXTENSIONS.values())


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 600_000
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _delete_all(connection: sqlite3.Connection, tables: Iterable[str]) -> None:
    existing = _tables(connection)
    for table in tables:
        if table in existing:
            connection.execute(f'DELETE FROM "{table}"')


def _retain_project_analysis_tasks(
    connection: sqlite3.Connection,
    project_ids: list[int],
) -> None:
    """仅保留每个演示项目最新的已完成分析结果，并移除全部调用参数。

    项目分析响应是剧本页的只读展示数据；请求参数可能包含模型配置或密钥，
    所以快照只保留 ``novel_id``，其余 AI 任务仍全部删除。
    """
    if "ai_tasks" not in _tables(connection):
        return
    columns = {
        str(row[1]) for row in connection.execute('PRAGMA table_info("ai_tasks")')
    }
    required = {
        "id",
        "task_type",
        "status",
        "request_params",
        "response_data",
        "created_at",
    }
    if not required.issubset(columns):
        connection.execute('DELETE FROM "ai_tasks"')
        return

    selected_projects = set(project_ids)
    retained: dict[int, str] = {}
    rows = connection.execute(
        """
        SELECT id, request_params
        FROM ai_tasks
        WHERE task_type=? AND status=? AND response_data IS NOT NULL
        ORDER BY created_at DESC
        """,
        (
            AiTaskTypeEnum.project_analysis.value,
            TaskStatusEnum.completed.value,
        ),
    ).fetchall()
    for task_id, raw_params in rows:
        try:
            params = json.loads(raw_params) if isinstance(raw_params, str) else raw_params
            novel_id = int(params.get("novel_id")) if isinstance(params, dict) else 0
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if novel_id in selected_projects and novel_id not in retained:
            retained[novel_id] = str(task_id)

    retained_ids = list(retained.values())
    if retained_ids:
        placeholders = ",".join("?" for _ in retained_ids)
        connection.execute(
            f'DELETE FROM "ai_tasks" WHERE id NOT IN ({placeholders})',
            retained_ids,
        )
        for novel_id, task_id in retained.items():
            assignments = ["request_params=?"]
            values: list[object] = [
                json.dumps({"novel_id": novel_id}, separators=(",", ":")),
            ]
            for column, value in (("error_message", None), ("stage", None), ("progress", 100)):
                if column in columns:
                    assignments.append(f'"{column}"=?')
                    values.append(value)
            values.append(task_id)
            connection.execute(
                f'UPDATE "ai_tasks" SET {", ".join(assignments)} WHERE id=?',
                values,
            )
    else:
        connection.execute('DELETE FROM "ai_tasks"')


def _scrub_json(value):
    if isinstance(value, dict):
        return {
            key: (
                None
                if any(part in str(key).casefold() for part in SENSITIVE_KEY_PARTS)
                else _scrub_json(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_json(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE_PATTERN.sub("[redacted]", value)
    return value


def _scrub_json_columns(connection: sqlite3.Connection) -> None:
    for table in sorted(_tables(connection)):
        columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        json_columns = [row[1] for row in columns if "JSON" in str(row[2]).upper()]
        if not json_columns:
            continue
        primary_keys = [row[1] for row in columns if row[5]]
        if len(primary_keys) != 1:
            continue
        primary_key = primary_keys[0]
        for column in json_columns:
            rows = connection.execute(
                f'SELECT "{primary_key}", "{column}" FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL'
            ).fetchall()
            for row_id, raw in rows:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, json.JSONDecodeError):
                    continue
                scrubbed = json.dumps(
                    _scrub_json(parsed), ensure_ascii=False, separators=(",", ":")
                )
                connection.execute(
                    f'UPDATE "{table}" SET "{column}"=? '
                    f'WHERE "{primary_key}"=?',
                    (scrubbed, row_id),
                )


def _prune_database(
    connection: sqlite3.Connection,
    project_ids: list[int],
    username: str,
    password: str,
    team_name: str,
) -> None:
    placeholders = ",".join("?" for _ in project_ids)
    existing_ids = {
        int(row[0])
        for row in connection.execute(
            f"SELECT id FROM novels WHERE id IN ({placeholders})", project_ids
        )
    }
    missing = sorted(set(project_ids) - existing_ids)
    if missing:
        raise ValueError(f"项目不存在: {missing}")

    connection.execute("PRAGMA foreign_keys=ON")
    # 部分开发库由兼容迁移补列后，历史索引尚未回填完整。只在备份副本中重建，
    # 既不触碰源库，也避免后续 DELETE 因损坏索引报 database malformed。
    connection.execute("REINDEX")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        f"DELETE FROM novels WHERE id NOT IN ({placeholders})", project_ids
    )

    _retain_project_analysis_tasks(connection, project_ids)
    _delete_all(
        connection,
        (
            "remake_uploads",
            "model_usage_records",
            "balance_transactions",
            "team_invites",
            "user_sessions",
            "ai_model_configs",
        ),
    )
    if "videos" in _tables(connection):
        connection.execute("DELETE FROM videos WHERE url IS NULL OR url = ''")
        connection.execute("UPDATE videos SET external_task_id=NULL, status=3")
    # 演示站不加载全量系统媒体库；项目素材自身仍由下面的引用扫描保留。
    _delete_all(connection, ("audio_references", "digital_humans"))

    _delete_all(connection, ("team_members", "users", "teams"))
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO users (
            id, created_at, updated_at, username, password_hash, nickname,
            avatar_url, unionid, openid, is_super_admin, status
        ) VALUES (1, ?, ?, ?, ?, '在线演示', '', NULL, NULL, 0, 1)
        """,
        (now, now, username, _hash_password(password)),
    )
    connection.execute(
        """
        INSERT INTO teams (
            id, created_at, updated_at, name, balance, model_config_source,
            status, member_limit, owner_user_id
        ) VALUES (1, ?, ?, ?, 0, 'official', 1, 1, 1)
        """,
        (now, now, team_name),
    )
    connection.execute(
        """
        INSERT INTO team_members (
            id, created_at, updated_at, role, status, total_cost, cost_limit,
            team_id, user_id
        ) VALUES (1, ?, ?, 'viewer', 1, 0, 0, 1, 1)
        """,
        (now, now),
    )
    connection.execute(
        """
        UPDATE novels SET
            team_id=1,
            created_by=1,
            video_model_config_id=NULL,
            narrator_audio_reference_id=NULL,
            creation_idempotency_key=NULL,
            creation_payload_hash=NULL
        """
    )
    if "remake_sources" in _tables(connection):
        connection.execute(
            """
            UPDATE remake_sources SET
                team_id=1,
                created_by=1,
                analysis_task_id=NULL
            """
        )

    _scrub_json_columns(connection)
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"演示快照外键校验失败，共 {len(violations)} 项")
    connection.commit()
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("VACUUM")


def _walk_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, str):
        yield value


def _local_media_path(raw: str) -> str | None:
    candidate = raw.strip()
    if candidate.startswith(("http://", "https://")):
        return None
    for prefix in MEDIA_PREFIXES:
        if candidate.startswith(prefix):
            relative = candidate[len(prefix):].split("?", 1)[0].split("#", 1)[0]
            return relative or None
    return None


def _replace_remote(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {key: _replace_remote(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_remote(item, replacements) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _rewrite_remote_references(
    connection: sqlite3.Connection, replacements: dict[str, str]
) -> None:
    if not replacements:
        return
    for table in sorted(_tables(connection)):
        columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        primary_keys = [row[1] for row in columns if row[5]]
        if len(primary_keys) != 1:
            continue
        primary_key = primary_keys[0]
        for column_row in columns:
            column = column_row[1]
            column_type = str(column_row[2]).upper()
            if not any(kind in column_type for kind in ("CHAR", "TEXT", "JSON")):
                continue
            rows = connection.execute(
                f'SELECT "{primary_key}", "{column}" FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL'
            ).fetchall()
            for row_id, raw in rows:
                if not isinstance(raw, str):
                    continue
                if "JSON" in column_type:
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    rewritten = _replace_remote(parsed, replacements)
                    if rewritten == parsed:
                        continue
                    value = json.dumps(
                        rewritten, ensure_ascii=False, separators=(",", ":")
                    )
                else:
                    value = replacements.get(raw)
                    if value is None:
                        continue
                connection.execute(
                    f'UPDATE "{table}" SET "{column}"=? '
                    f'WHERE "{primary_key}"=?',
                    (value, row_id),
                )


def _vendor_remote_media(
    connection: sqlite3.Connection,
    destination_root: Path,
    *,
    max_file_bytes: int = 512 * 1024 * 1024,
    max_total_bytes: int = 1024 * 1024 * 1024,
) -> tuple[int, int]:
    _, remote = _referenced_media(connection)
    replacements: dict[str, str] = {}
    downloaded_bytes = 0
    for url in sorted(remote):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("远程媒体必须使用 HTTPS")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "NovelVids-Demo-Snapshot/1.0"},
        )
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        path_extension = Path(unquote(parsed.path)).suffix.lower()
        if path_extension not in ALLOWED_MEDIA_EXTENSIONS:
            path_extension = ""
        relative: str | None = None
        temporary = destination_root / "vendor" / f".{digest}.part"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_length = int(response.headers.get("Content-Length") or 0)
                if content_length > max_file_bytes:
                    raise RuntimeError("远程媒体单文件超过快照限制")
                content_type = response.headers.get_content_type().lower()
                extension = path_extension or CONTENT_TYPE_EXTENSIONS.get(content_type)
                if not extension:
                    raise RuntimeError(f"不支持的远程媒体类型: {content_type}")
                size = 0
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > max_file_bytes:
                            raise RuntimeError("远程媒体单文件超过快照限制")
                        if downloaded_bytes + size > max_total_bytes:
                            raise RuntimeError("远程媒体总量超过快照限制")
                        output.write(chunk)
                relative = f"vendor/{digest}{extension}"
                destination = destination_root / relative
                temporary.replace(destination)
                downloaded_bytes += size
        finally:
            temporary.unlink(missing_ok=True)
        replacements[url] = f"/media/{relative}"

    _rewrite_remote_references(connection, replacements)
    if "remake_sources" in _tables(connection):
        connection.execute(
            """
            UPDATE remake_sources
            SET storage_provider='local', object_key=substr(object_key, 8)
            WHERE object_key LIKE '/media/%'
            """
        )
    connection.commit()
    return len(replacements), downloaded_bytes


def _referenced_media(connection: sqlite3.Connection) -> tuple[set[str], set[str]]:
    local: set[str] = set()
    remote: set[str] = set()
    for table in sorted(_tables(connection)):
        columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        text_columns = [
            row[1]
            for row in columns
            if any(kind in str(row[2]).upper() for kind in ("CHAR", "TEXT", "JSON"))
        ]
        if not text_columns:
            continue
        projection = ", ".join(f'"{column}"' for column in text_columns)
        for row in connection.execute(f'SELECT {projection} FROM "{table}"'):
            for raw in row:
                if not isinstance(raw, str) or not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = raw
                for value in _walk_strings(parsed):
                    relative = _local_media_path(value)
                    if relative:
                        local.add(relative)
                    elif value.startswith(("http://", "https://")):
                        remote.add(value)

    if "remake_sources" in _tables(connection):
        for provider, object_key in connection.execute(
            "SELECT storage_provider, object_key FROM remake_sources"
        ):
            if provider == "local" and object_key:
                local.add(str(object_key))
            elif object_key:
                remote.add(str(object_key))
    return local, remote


def _copy_media(
    connection: sqlite3.Connection,
    source_root: Path,
    destination_root: Path,
) -> tuple[int, int]:
    local, remote = _referenced_media(connection)
    if remote:
        hosts = sorted(
            {urlparse(item).hostname or "non-http-object-key" for item in remote}
        )
        raise RuntimeError(
            "演示数据仍引用远程媒体，拒绝生成无 OSS 快照；来源: " + ", ".join(hosts)
        )

    source_root = source_root.resolve()
    copied = 0
    copied_bytes = 0
    for relative in sorted(local):
        source = (source_root / relative).resolve()
        destination = destination_root / relative
        try:
            source.relative_to(source_root)
        except ValueError as exc:
            raise RuntimeError(f"媒体路径越界: {relative}") from exc
        if not source.is_file():
            if destination.is_file():
                copied += 1
                copied_bytes += destination.stat().st_size
                continue
            raise FileNotFoundError(f"引用的媒体文件不存在: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
        copied_bytes += source.stat().st_size
    derivative_files, derivative_bytes = _generate_image_derivatives(
        connection,
        destination_root,
    )
    poster_files, poster_bytes = _generate_video_posters(
        connection,
        destination_root,
    )
    return (
        copied + derivative_files + poster_files,
        copied_bytes + derivative_bytes + poster_bytes,
    )


def _generate_image_derivatives(
    connection: sqlite3.Connection,
    destination_root: Path,
) -> tuple[int, int]:
    """为快照中的所有受管图片补齐派生图。"""
    references, _remote = _referenced_media(connection)
    files = total_bytes = 0
    for relative in sorted(references):
        if Path(relative).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        source = destination_root / relative
        if not source.is_file():
            continue
        try:
            written = write_local_cover_derivatives(
                destination_root,
                f"/media/{relative}",
                source.read_bytes(),
                force=False,
            )
        except ValueError:
            continue
        for path in written.values():
            files += 1
            total_bytes += path.stat().st_size
    return files, total_bytes


def _generate_video_posters(
    connection: sqlite3.Connection,
    destination_root: Path,
) -> tuple[int, int]:
    """提取生成视频首帧海报，并把稳定引用写入快照中的视频元数据。"""
    if "videos" not in _tables(connection):
        return 0, 0
    rows = connection.execute(
        "SELECT id, url, metadata FROM videos "
        "WHERE status = ? AND url IS NOT NULL AND url != ''",
        (TaskStatusEnum.completed.value,),
    ).fetchall()
    files = total_bytes = 0
    extractor = VideoPosterService()
    for video_id, video_url, raw_metadata in rows:
        relative = _local_media_path(str(video_url))
        if not relative or Path(relative).suffix.lower() not in {
            ".mp4",
            ".mov",
            ".webm",
        }:
            continue
        source = destination_root / relative
        if not source.is_file():
            continue
        with TemporaryDirectory(prefix=f"snapshot-poster-{video_id}-") as directory:
            frame = Path(directory) / "poster.png"
            try:
                extractor._extract_with_ffmpeg(source, frame)
                derivatives = render_cover_derivatives(frame.read_bytes())
            except (OSError, ValueError, RuntimeError):
                continue
        poster_metadata: dict[str, str] = {}
        for kind, data in derivatives.items():
            reference = video_poster_reference(f"/media/{relative}", kind)
            destination = local_media_path(destination_root, reference)
            if destination is None:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            files += 1
            total_bytes += len(data)
            poster_metadata[
                "poster_thumbnail_url" if kind == "thumbnail" else "poster_url"
            ] = str(reference)
        try:
            metadata = (
                json.loads(raw_metadata)
                if isinstance(raw_metadata, str)
                else raw_metadata
            )
        except json.JSONDecodeError:
            metadata = {}
        metadata = metadata if isinstance(metadata, dict) else {}
        connection.execute(
            "UPDATE videos SET metadata = ? WHERE id = ?",
            (json.dumps({**metadata, **poster_metadata}, ensure_ascii=False), video_id),
        )
    connection.commit()
    return files, total_bytes


def create_snapshot(
    source_db: Path,
    source_media: Path,
    output_dir: Path,
    project_ids: list[int],
    username: str,
    password: str,
    team_name: str,
    vendor_remote: bool = False,
) -> dict[str, int]:
    if not project_ids:
        raise ValueError("至少指定一个 --project-id")
    if output_dir.exists():
        raise FileExistsError(f"输出目录已存在: {output_dir}")
    output_dir.mkdir(parents=True)
    destination_db = output_dir / "novelvids.db"
    destination_media = output_dir / "media"

    source_uri = f"file:{source_db.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(
        destination_db
    ) as destination:
        source.backup(destination)
        _prune_database(destination, project_ids, username, password, team_name)
        if vendor_remote:
            _vendor_remote_media(destination, destination_media)
        media_files, media_bytes = _copy_media(
            destination, source_media, destination_media
        )
        projects = destination.execute("SELECT COUNT(*) FROM novels").fetchone()[0]

    return {
        "projects": int(projects),
        "media_files": media_files,
        "media_bytes": media_bytes,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--source-media", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--project-id", type=int, action="append", required=True)
    parser.add_argument("--username", default="demo")
    parser.add_argument("--password", required=True)
    parser.add_argument("--team-name", default="在线演示团队")
    parser.add_argument(
        "--vendor-remote",
        action="store_true",
        help="下载并本地化所有 HTTPS 远程媒体引用",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = create_snapshot(
        args.source_db,
        args.source_media,
        args.output_dir,
        args.project_id,
        args.username,
        args.password,
        args.team_name,
        args.vendor_remote,
    )
    print(
        f"snapshot ready: projects={result['projects']} "
        f"media_files={result['media_files']} media_bytes={result['media_bytes']}"
    )


if __name__ == "__main__":
    main()
