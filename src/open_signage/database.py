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
        if existing and (
            "'stream'" not in existing["sql"]
            or "'pdf'" not in existing["sql"]
            or "muted" not in {row["name"] for row in connection.execute("PRAGMA table_info(content)")}
        ):
            connection.execute("ALTER TABLE content RENAME TO content_legacy")

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('image', 'video', 'pdf', 'website', 'stream')),
                source TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL DEFAULT 10
                    CHECK(duration_seconds BETWEEN 1 AND 86400),
                position INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                muted INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_content_playlist
            ON content(enabled, position, id);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        if existing and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'content_legacy'"
        ).fetchone():
            connection.execute(
                """
                INSERT INTO content(
                    id, name, kind, source, duration_seconds, position, enabled, muted, created_at
                )
                SELECT id, name, kind, source, duration_seconds, position, enabled, 1, created_at
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
