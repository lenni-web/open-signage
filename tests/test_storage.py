"""Datenbank, Speicherprüfung, Bereinigung und Backups."""

import hashlib
import os
import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage import backup
from open_signage.database import connect, initialize, integrity_check_if_due
from open_signage.main import app
from open_signage.media_files import file_sha256

from helpers import VALID_PNG


def test_sqlite_busy_timeout_and_integrity_check(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    with connect() as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    result = integrity_check_if_due(timedelta(0))
    assert result["ok"] is True
    assert result["results"] == ["ok"]


def test_existing_playlist_is_migrated_without_data_loss(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    database = tmp_path / "open-signage.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('image', 'video', 'website')),
                source TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL DEFAULT 10,
                position INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO content(name, kind, source)
            VALUES ('Bestehend', 'website', 'https://example.org');
            """
        )

    initialize()

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT name, kind, muted FROM content"
        ).fetchone()
        assert row == ("Bestehend", "website", 1)
        index = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_content_playlist'"
        ).fetchone()
        assert index is not None


def test_storage_cleanup_removes_unused_library_media(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        media = client.post("/api/media-library", files={"file": ("unused.png", VALID_PNG, "image/png")}).json()
        assert client.get("/api/system/storage").json()["unused_media_count"] == 1
        cleaned = client.post("/api/system/storage/cleanup").json()
        assert cleaned["removed_media"] == 1
        assert client.get("/api/media-library").json() == []
    assert not (tmp_path / "media" / Path(media["source"]).name).exists()


def test_backup_can_be_created_downloaded_and_restored(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post("/api/content/website", json={"name": "Gesichert", "url": "https://example.org"})
        backup = client.post("/api/system/backups", json={"include_media": False})
        assert backup.status_code == 201
        archive = client.get(f"/api/system/backups/{backup.json()['name']}")
        assert archive.status_code == 200
        client.delete(f"/api/content/{created.json()['id']}")
        restored = client.post(
            "/api/system/backups/restore",
            files={"file": ("backup.zip", archive.content, "application/zip")},
        )
        assert restored.status_code == 200
        assert [item["name"] for item in client.get("/api/content").json()] == ["Gesichert"]


def test_security_status_reports_integrity_and_backup(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        status = client.get("/api/system/security-status")
    assert status.status_code == 200
    assert status.json()["checks"]["database_integrity_ok"] is True
    assert status.json()["checks"]["backup_available"] is True


def test_storage_audit_finds_duplicates_missing_and_orphans(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        first = client.post("/api/media-library", files={"file": ("a.png", VALID_PNG, "image/png")}).json()
        second = client.post("/api/media-library", files={"file": ("b.png", VALID_PNG, "image/png")}).json()
        third = client.post("/api/media-library", files={"file": ("c.png", VALID_PNG, "image/png")}).json()
        (tmp_path / "media" / Path(first["source"]).name).unlink()
        (tmp_path / "media" / "orphan.bin").write_bytes(b"orphan")
        audit = client.get("/api/system/storage").json()
        assert first["id"] in audit["missing_media_ids"]
        assert audit["orphan_file_count"] == 1
        assert any({second["id"], third["id"]}.issubset(group) for group in map(set, audit["duplicate_groups"]))
        cleaned = client.post("/api/system/storage/orphans/cleanup").json()
        assert cleaned["removed_files"] == 1


def test_cached_file_hash_is_invalidated_when_file_changes(tmp_path: Path):
    path = tmp_path / "datei.bin"
    path.write_bytes(b"erste")
    first = file_sha256(path)
    path.write_bytes(b"zweit")
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert file_sha256(path) != first
    assert file_sha256(path) == hashlib.sha256(b"zweit").hexdigest()


def test_restore_extracts_inside_data_directory_with_media(tmp_path: Path, monkeypatch):
    # /tmp kann ein anderes Dateisystem sein (tmpfs); Dateien werden danach verschoben.
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path / "data"))
    used = []
    original = backup.tempfile.TemporaryDirectory

    def recording(*args, **kwargs):
        used.append(kwargs.get("dir"))
        return original(*args, **kwargs)

    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post("/api/content/upload", files={"file": ("bild.png", VALID_PNG, "image/png")}).json()
        archive = client.get(f"/api/system/backups/{client.post('/api/system/backups', json={'include_media': True}).json()['name']}")
        media_file = tmp_path / "data" / "media" / Path(uploaded["source"]).name
        media_file.unlink()
        monkeypatch.setattr(backup.tempfile, "TemporaryDirectory", recording)
        restored = client.post("/api/system/backups/restore",
                               files={"file": ("backup.zip", archive.content, "application/zip")})
        assert restored.status_code == 200
    assert media_file.is_file()
    assert Path(used[-1]) == (tmp_path / "data").resolve()
    assert not list((tmp_path / "data").glob(".restore-*"))
