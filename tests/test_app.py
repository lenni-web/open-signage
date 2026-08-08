import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_signage.database import initialize
from open_signage.main import app
from open_signage.media_probe import evaluate_video_probe
from open_signage.system_update import request_update, update_status
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


def test_raspberry_pi_templates_have_expected_placeholders():
    service = (PROJECT_ROOT / "deploy/open-signage.service").read_text(encoding="utf-8")
    kiosk = (PROJECT_ROOT / "deploy/open-signage-kiosk").read_text(encoding="utf-8")

    assert "@@PORT@@" in service
    assert "Restart=on-failure" in service
    assert "@@PLAYER_URL@@" in kiosk
    assert "@@HEALTH_URL@@" in kiosk
    assert "--autoplay-policy=no-user-gesture-required" in kiosk
    assert "--ozone-platform=wayland" in kiosk

    installer = (PROJECT_ROOT / "scripts/install-raspberry-pi.sh").read_text(
        encoding="utf-8"
    )
    assert "rpd-wayland-core" in installer
    assert "raspi-config nonint do_boot_behaviour B4" in installer
    assert 'KIOSK_USER="signage"' in installer
    assert "ffmpeg" in installer


def test_compatible_mp4_probe_has_no_warning():
    result = evaluate_video_probe(
        ".mp4",
        {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )
    assert result["compatible"] is True
    assert result["warnings"] == []


def test_incompatible_mp4_probe_explains_supported_format():
    result = evaluate_video_probe(
        ".mp4",
        {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc"},
                {"codec_type": "audio", "codec_name": "ac3"},
            ],
        },
    )
    assert result["compatible"] is False
    assert any("H.264" in warning for warning in result["warnings"])
    assert any("AAC" in warning for warning in result["warnings"])
    assert "WebM" in result["recommendation"]


def test_video_upload_returns_compatibility_result(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    compatibility = {
        "checked": True,
        "compatible": False,
        "warnings": ["Für zuverlässige Wiedergabe H.264/AVC verwenden."],
        "recommendation": "Empfohlen: MP4 mit H.264/AVC und AAC.",
    }
    monkeypatch.setattr(
        "open_signage.main.inspect_video", lambda _path: compatibility
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/content/upload",
            data={"duration_seconds": "10"},
            files={"file": ("video.mp4", b"test", "video/mp4")},
        )

    assert response.status_code == 201
    assert response.json()["kind"] == "video"
    assert response.json()["compatibility"] == compatibility


def test_system_info_endpoint_has_device_and_network_sections(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/system/info")

    assert response.status_code == 200
    assert response.json()["hostname"]
    assert set(response.json()["network"]) == {"wlan", "ethernet"}
    assert response.json()["disk"]["total_bytes"] > 0


def test_system_update_request_is_queued_once(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_SIGNAGE_ENABLE_SYSTEM_UPDATE", "1")

    queued = request_update()

    assert queued["status"] == "queued"
    assert update_status()["status"] == "queued"
    assert (tmp_path / "update.request").exists()
    with pytest.raises(RuntimeError, match="läuft bereits"):
        request_update()


def test_system_update_api_returns_conflict_while_queued(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_SIGNAGE_ENABLE_SYSTEM_UPDATE", "1")
    with TestClient(app) as client:
        first = client.post("/api/system/update")
        second = client.post("/api/system/update")

    assert first.status_code == 202
    assert second.status_code == 409


def test_update_service_is_installed_without_sudo_access():
    installer = (PROJECT_ROOT / "scripts/install-raspberry-pi.sh").read_text(
        encoding="utf-8"
    )
    update_service = (
        PROJECT_ROOT / "deploy/open-signage-update.service"
    ).read_text(encoding="utf-8")
    update_path = (PROJECT_ROOT / "deploy/open-signage-update.path").read_text(
        encoding="utf-8"
    )
    update_script = (
        PROJECT_ROOT / "deploy/open-signage-system-update"
    ).read_text(encoding="utf-8")

    assert "open-signage-update.path" in installer
    assert "  iw \\" in installer
    assert "ExecStart=/usr/local/sbin/open-signage-system-update" in update_service
    assert "PathExists=/var/lib/open-signage/update.request" in update_path
    assert "apt-get update &&" in update_script
    assert "apt-get upgrade -y" in update_script
    assert "sudo" not in update_script


def test_admin_contains_system_navigation_and_update_controls():
    admin = (PROJECT_ROOT / "src/open_signage/static/admin.html").read_text(
        encoding="utf-8"
    )

    assert 'data-page="system-page"' in admin
    assert 'id="wlan-info"' in admin
    assert 'id="ethernet-info"' in admin
    assert 'id="system-update"' in admin


def test_pdf_can_be_uploaded_and_deleted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        uploaded = client.post(
            "/api/content/upload",
            data={"duration_seconds": "20"},
            files={
                "file": (
                    "hinweis.pdf",
                    b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF",
                    "application/pdf",
                )
            },
        )
        assert uploaded.status_code == 201
        item = uploaded.json()
        assert item["kind"] == "pdf"
        stored = tmp_path / "media" / Path(item["source"]).name
        assert stored.exists()

        deleted = client.delete(f"/api/content/{item['id']}")
        assert deleted.status_code == 204
        assert not stored.exists()


def test_invalid_pdf_is_rejected_and_removed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/content/upload",
            files={"file": ("falsch.pdf", b"kein pdf", "application/pdf")},
        )

    assert response.status_code == 415
    assert list((tmp_path / "media").iterdir()) == []
