from __future__ import annotations

import os
import sqlite3
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
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with connect() as connection:
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
