from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def data_dir() -> Path:
    path = Path(os.environ.get("OPEN_SIGNAGE_DATA_DIR", "data")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_dir() -> Path:
    path = data_dir() / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "open-signage.sqlite3"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        existing = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'content'"
        ).fetchone()
        existing_columns = (
            {row["name"] for row in connection.execute("PRAGMA table_info(content)")}
            if existing else set()
        )
        if existing and (
            "'stream'" not in existing["sql"]
            or "'pdf'" not in existing["sql"]
            or "'text'" not in existing["sql"]
            or "muted" not in existing_columns
            or "media_id" not in existing_columns
        ):
            connection.execute("ALTER TABLE content RENAME TO content_legacy")

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 0,
                schedule_enabled INTEGER NOT NULL DEFAULT 0,
                schedule_start TEXT,
                schedule_end TEXT,
                schedule_weekdays TEXT,
                schedule_daily_start TEXT,
                schedule_daily_end TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO playlists(id, name, active)
            VALUES (1, 'Standard', 1);

            CREATE TABLE IF NOT EXISTS media_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('image', 'video')),
                source TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                original_source TEXT,
                thumbnail_source TEXT,
                width INTEGER,
                height INTEGER,
                category TEXT NOT NULL DEFAULT '',
                metadata_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('image', 'video', 'pdf', 'website', 'stream', 'text')),
                source TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL DEFAULT 10
                    CHECK(duration_seconds BETWEEN 1 AND 86400),
                position INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                muted INTEGER NOT NULL DEFAULT 1,
                play_to_end INTEGER NOT NULL DEFAULT 0,
                text_config TEXT,
                media_id INTEGER REFERENCES media_library(id) ON DELETE RESTRICT,
                schedule_start TEXT,
                schedule_end TEXT,
                schedule_weekdays TEXT,
                schedule_daily_start TEXT,
                schedule_daily_end TEXT,
                playlist_id INTEGER NOT NULL DEFAULT 1 REFERENCES playlists(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_content_playlist
            ON content(enabled, position, id);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_sessions (
                token_hash TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                client_key TEXT PRIMARY KEY,
                failed_count INTEGER NOT NULL DEFAULT 0,
                window_started TEXT NOT NULL,
                blocked_until TEXT
            );
            CREATE TABLE IF NOT EXISTS maintenance_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversion_jobs (
                id TEXT PRIMARY KEY,
                media_id INTEGER NOT NULL REFERENCES media_library(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'failed')),
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS registered_devices (
                device_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                registered_at TEXT NOT NULL,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS player_status (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                last_seen TEXT NOT NULL,
                state TEXT NOT NULL,
                content_id INTEGER,
                content_name TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS player_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                content_name TEXT
            );
            """
        )
        if existing and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'content_legacy'"
        ).fetchone():
            muted_expression = "muted" if "muted" in existing_columns else "1"
            text_expression = "text_config" if "text_config" in existing_columns else "NULL"
            connection.execute(
                f"""
                INSERT INTO content(
                    id, name, kind, source, duration_seconds, position, enabled, muted, text_config, media_id, playlist_id, created_at
                )
                SELECT id, name, kind, source, duration_seconds, position, enabled,
                       {muted_expression}, {text_expression}, NULL, 1, created_at
                FROM content_legacy
                """
            )
            connection.execute("DROP TABLE content_legacy")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_content_playlist
                ON content(enabled, position, id)
                """
            )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(content)")}
        for name, definition in {
            "schedule_start": "TEXT",
            "schedule_end": "TEXT",
            "schedule_weekdays": "TEXT",
            "schedule_daily_start": "TEXT",
            "schedule_daily_end": "TEXT",
            "playlist_id": "INTEGER NOT NULL DEFAULT 1",
            "play_to_end": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE content ADD COLUMN {name} {definition}")
        media_columns = {row["name"] for row in connection.execute("PRAGMA table_info(media_library)")}
        for name, definition in {
            "original_source": "TEXT", "thumbnail_source": "TEXT",
            "width": "INTEGER", "height": "INTEGER",
            "category": "TEXT NOT NULL DEFAULT ''", "metadata_json": "TEXT",
        }.items():
            if name not in media_columns:
                connection.execute(f"ALTER TABLE media_library ADD COLUMN {name} {definition}")
        playlist_columns = {row["name"] for row in connection.execute("PRAGMA table_info(playlists)")}
        for name, definition in {
            "schedule_enabled": "INTEGER NOT NULL DEFAULT 0", "schedule_start": "TEXT",
            "schedule_end": "TEXT", "schedule_weekdays": "TEXT",
            "schedule_daily_start": "TEXT", "schedule_daily_end": "TEXT",
        }.items():
            if name not in playlist_columns:
                connection.execute(f"ALTER TABLE playlists ADD COLUMN {name} {definition}")
        connection.execute(
            "UPDATE conversion_jobs SET status = 'failed', "
            "message = 'Konvertierung wurde durch einen Anwendungsneustart abgebrochen', "
            "updated_at = ? WHERE status IN ('queued', 'running')",
            (datetime.now(UTC).isoformat(),),
        )


def integrity_check_if_due(interval: timedelta = timedelta(days=1)) -> dict:
    """Run SQLite's complete integrity check at most once per interval."""
    now = datetime.now(UTC)
    with connect() as connection:
        row = connection.execute(
            "SELECT value FROM maintenance_state WHERE key = 'last_integrity_check'"
        ).fetchone()
        if row:
            try:
                last = datetime.fromisoformat(row["value"])
                if now - last < interval:
                    return {"checked": False, "ok": True, "last_checked": row["value"]}
            except ValueError:
                pass
        results = [item[0] for item in connection.execute("PRAGMA integrity_check").fetchall()]
        ok = results == ["ok"]
        connection.execute(
            "INSERT INTO maintenance_state(key, value) VALUES ('last_integrity_check', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (now.isoformat(),),
        )
        connection.execute(
            "INSERT INTO maintenance_state(key, value) VALUES ('last_integrity_result', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(results),),
        )
    return {"checked": True, "ok": ok, "last_checked": now.isoformat(), "results": results}
