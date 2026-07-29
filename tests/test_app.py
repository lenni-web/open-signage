import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage.database import initialize
from open_signage.main import app
from open_signage.version import __version__

PROJECT_ROOT = Path(__file__).parents[1]


def test_health_and_website_crud(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": __version__}

        created = client.post(
            "/api/content/website",
            json={
                "name": "Beispiel",
                "url": "https://example.org",
                "duration_seconds": 15,
            },
        )
        assert created.status_code == 201
        item = created.json()
        assert item["kind"] == "website"
        assert item["enabled"] is True

        updated = client.patch(
            f"/api/content/{item['id']}",
            json={"duration_seconds": 20, "enabled": False},
        )
        assert updated.status_code == 200
        assert updated.json()["duration_seconds"] == 20
        assert updated.json()["enabled"] is False

        assert client.get("/api/content?enabled_only=true").json() == []
        assert client.delete(f"/api/content/{item['id']}").status_code == 204


def test_invalid_website_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/content/website",
            json={"name": "Falsch", "url": "javascript:alert(1)", "duration_seconds": 10},
        )
        assert response.status_code == 422


def test_owncast_stream_is_normalized_and_can_enable_sound(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/content/stream",
            json={
                "name": "Live",
                "url": "https://stream.mg-stade.de/embed/video?initiallyMuted=true",
                "duration_seconds": 3600,
                "muted": True,
            },
        )
        assert response.status_code == 201
        item = response.json()
        assert item["kind"] == "stream"
        assert item["source"] == "https://stream.mg-stade.de/hls/stream.m3u8"
        assert item["muted"] is True

        updated = client.patch(f"/api/content/{item['id']}", json={"muted": False})
        assert updated.status_code == 200
        assert updated.json()["muted"] is False


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


def test_current_version_is_documented_in_changelog():
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in changelog
