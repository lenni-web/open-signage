import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_signage.database import initialize
from open_signage.application_update import request_update as request_application_update
from open_signage.application_update import update_status as application_update_status
from open_signage.main import app, scheduled_now
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
        assert client.get("/api/content").status_code == 401
        assert client.post(
            "/api/system/login", json={"password": "open-signage"}
        ).status_code == 200

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

        assert client.get("/api/player/content").json() == []
        assert client.delete(f"/api/content/{item['id']}").status_code == 204


def test_invalid_website_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/website",
            json={"name": "Falsch", "url": "javascript:alert(1)", "duration_seconds": 10},
        )
        assert response.status_code == 422


def test_owncast_stream_is_normalized_and_can_enable_sound(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
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
        client.post("/api/system/login", json={"password": "open-signage"})
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
        assert client.get("/api/system/info").status_code == 401
        assert client.post(
            "/api/system/login", json={"password": "open-signage"}
        ).status_code == 200
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
        client.post("/api/system/login", json={"password": "open-signage"})
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

    application_script = (
        PROJECT_ROOT / "deploy/open-signage-application-update"
    ).read_text(encoding="utf-8")
    application_service = (
        PROJECT_ROOT / "deploy/open-signage-application-update.service"
    ).read_text(encoding="utf-8")
    application_path = (
        PROJECT_ROOT / "deploy/open-signage-application-update.path"
    ).read_text(encoding="utf-8")
    assert "open-signage-application-update.path" in installer
    assert "git -C" in application_script
    assert "systemctl stop open-signage.service" in application_script
    assert "Healthcheck fehlgeschlagen" in application_script
    assert "ExecStart=/usr/local/sbin/open-signage-application-update" in application_service
    assert "ExecStartPre=/bin/sleep 2" in application_service
    assert "PathExists=/var/lib/open-signage/application-update.request" in application_path
    assert "systemctl daemon-reload" in application_script


def test_admin_contains_system_navigation_and_update_controls():
    admin = (PROJECT_ROOT / "src/open_signage/static/admin.html").read_text(
        encoding="utf-8"
    )

    assert 'data-page="system-page"' in admin
    assert 'id="wlan-info"' in admin
    assert 'id="ethernet-info"' in admin
    assert 'id="system-update"' in admin
    assert 'id="login-form"' in admin
    assert 'id="screen-settings-form"' in admin
    assert 'id="application-update"' in admin
    assert 'id="login-screen"' in admin
    assert 'id="admin-app" hidden' in admin
    assert 'id="logout"' in admin
    assert 'data-page="library-page"' in admin
    assert 'id="media-library"' in admin
    assert 'id="text-library-image"' in admin
    assert 'name="shadow_intensity"' in admin
    assert admin.count('class="card update-card collapsible-card"') == 2
    assert 'class="card system-overview collapsible-card"' in admin
    assert 'value="12"' in admin


def test_screen_name_and_password_are_persisted_and_protected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/settings").json() == {"screen_name": "Open Signage"}
        assert client.patch(
            "/api/system/settings", json={"screen_name": "Foyer"}
        ).status_code == 401

        assert client.post(
            "/api/system/login", json={"password": "open-signage"}
        ).status_code == 200
        changed = client.patch(
            "/api/system/settings", json={"screen_name": "Foyer"}
        )
        assert changed.json() == {"screen_name": "Foyer"}
        assert client.get("/api/settings").json() == {"screen_name": "Foyer"}

        changed_password = client.post(
            "/api/system/password",
            json={
                "current_password": "open-signage",
                "new_password": "sicheres-passwort",
            },
        )
        assert changed_password.status_code == 200

    with TestClient(app) as client:
        assert client.post(
            "/api/system/login", json={"password": "open-signage"}
        ).status_code == 401
        assert client.post(
            "/api/system/login", json={"password": "sicheres-passwort"}
        ).status_code == 200


def test_website_default_duration_is_twelve_seconds(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/website",
            json={"name": "Web", "url": "https://example.org"},
        )
    assert response.status_code == 201
    assert response.json()["duration_seconds"] == 12


def test_pdf_can_be_uploaded_and_deleted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
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

        served = client.get(item["source"])
        assert served.headers["cache-control"] == "public, max-age=31536000, immutable"

        deleted = client.delete(f"/api/content/{item['id']}")
        assert deleted.status_code == 204
        assert not stored.exists()


def test_invalid_pdf_is_rejected_and_removed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/upload",
            files={"file": ("falsch.pdf", b"kein pdf", "application/pdf")},
        )

    assert response.status_code == 415
    assert list((tmp_path / "media").iterdir()) == []


def test_application_update_request_and_api_are_protected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_SIGNAGE_ENABLE_APPLICATION_UPDATE", "1")
    queued = request_application_update()
    assert queued["status"] == "queued"
    assert application_update_status()["status"] == "queued"

    (tmp_path / "application-update.request").unlink()
    with TestClient(app) as client:
        assert client.post("/api/system/application-update").status_code == 401
        client.post("/api/system/login", json={"password": "open-signage"})
        assert client.post("/api/system/application-update").status_code == 202


def test_logout_revokes_management_access(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        assert client.get("/api/content").status_code == 200
        assert client.post("/api/system/logout").status_code == 204
        assert client.get("/api/content").status_code == 401


def test_session_is_stored_for_server_restarts(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        cookie = client.cookies.get("open_signage_session")
    with TestClient(app) as restarted_client:
        restarted_client.cookies.set("open_signage_session", cookie)
        assert restarted_client.get("/api/system/session").status_code == 200


def test_text_content_can_be_previewed_by_player_edited_and_deleted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post(
            "/api/content/text",
            data={
                "name": "Begrüßung",
                "headline": "Willkommen",
                "subheadline": "Im Foyer",
                "body": "Die Veranstaltung beginnt um 18 Uhr.",
                "shadow_box": "true",
                "shadow_intensity": "dark",
                "duration_seconds": "12",
            },
            files={"background": ("foyer.jpg", b"image", "image/jpeg")},
        )
        assert created.status_code == 201
        item = created.json()
        assert item["kind"] == "text"
        assert item["text_config"]["headline"] == "Willkommen"
        assert item["text_config"]["shadow_box"] is True
        assert item["text_config"]["shadow_intensity"] == "dark"
        old_background = tmp_path / "media" / Path(item["source"]).name
        assert old_background.exists()
        assert client.get("/api/player/content").json()[0]["id"] == item["id"]

        edited = client.post(
            f"/api/content/{item['id']}/text",
            data={
                "name": "Neue Begrüßung",
                "headline": "Guten Abend",
                "subheadline": "",
                "body": "Beginn um 19 Uhr.",
                "duration_seconds": "20",
            },
        )
        assert edited.status_code == 200
        assert edited.json()["text_config"]["headline"] == "Guten Abend"
        assert edited.json()["text_config"]["shadow_box"] is False
        assert edited.json()["text_config"]["shadow_intensity"] == "medium"
        assert edited.json()["source"] == item["source"]

        assert client.delete(f"/api/content/{item['id']}").status_code == 204
        assert not old_background.exists()


def test_text_content_requires_image_and_some_text(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        wrong_image = client.post(
            "/api/content/text",
            data={"name": "Text", "headline": "Titel", "subheadline": "", "body": ""},
            files={"background": ("datei.pdf", b"pdf", "application/pdf")},
        )
        assert wrong_image.status_code == 415

        no_text = client.post(
            "/api/content/text",
            data={"name": "Leer", "headline": "", "subheadline": "", "body": ""},
            files={"background": ("bild.png", b"image", "image/png")},
        )
        assert no_text.status_code == 422
        assert not (tmp_path / "media").exists() or not list((tmp_path / "media").iterdir())

        invalid_intensity = client.post(
            "/api/content/text",
            data={
                "name": "Schatten",
                "headline": "Titel",
                "shadow_intensity": "maximum",
            },
            files={"background": ("bild.png", b"image", "image/png")},
        )
        assert invalid_intensity.status_code == 422


def test_media_library_reuses_files_for_playlist_and_text(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/media-library",
            files={"file": ("hintergrund.jpg", b"image", "image/jpeg")},
        )
        assert uploaded.status_code == 201
        media = uploaded.json()
        assert client.get("/api/media-library").json()[0]["id"] == media["id"]
        stored = tmp_path / "media" / Path(media["source"]).name
        assert stored.exists()

        playlist = client.post(
            f"/api/media-library/{media['id']}/playlist",
            json={"duration_seconds": 15},
        )
        assert playlist.status_code == 201
        playlist_item = playlist.json()
        assert playlist_item["media_id"] == media["id"]

        text = client.post(
            "/api/content/text",
            data={
                "name": "Hinweis",
                "headline": "Hallo",
                "library_media_id": str(media["id"]),
            },
        )
        assert text.status_code == 201
        text_item = text.json()
        assert text_item["source"] == media["source"]
        assert text_item["media_id"] == media["id"]

        blocked = client.delete(f"/api/media-library/{media['id']}")
        assert blocked.status_code == 409
        assert client.delete(f"/api/content/{playlist_item['id']}").status_code == 204
        assert stored.exists()
        assert client.delete(f"/api/content/{text_item['id']}").status_code == 204
        assert client.delete(f"/api/media-library/{media['id']}").status_code == 204
        assert not stored.exists()


def test_media_library_is_protected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/media-library").status_code == 401
        assert client.post(
            "/api/media-library",
            files={"file": ("bild.jpg", b"image", "image/jpeg")},
        ).status_code == 401


def test_content_schedule_controls_player_playlist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post(
            "/api/content/website",
            json={"name": "Termin", "url": "https://example.org"},
        ).json()
        future = client.patch(
            f"/api/content/{created['id']}",
            json={"schedule_start": "2099-01-01T12:00:00+00:00"},
        )
        assert future.status_code == 200
        assert client.get("/api/player/content").json() == []

        cleared = client.patch(
            f"/api/content/{created['id']}", json={"clear_schedule": True}
        )
        assert cleared.status_code == 200
        assert cleared.json()["schedule_start"] is None
        assert len(client.get("/api/player/content").json()) == 1


def test_overnight_and_weekday_schedules():
    monday_late = datetime.fromisoformat("2026-08-10T23:30:00+02:00")
    tuesday_early = datetime.fromisoformat("2026-08-11T01:30:00+02:00")
    item = {
        "schedule_start": None,
        "schedule_end": None,
        "schedule_weekdays": [0, 1],
        "schedule_daily_start": "22:00",
        "schedule_daily_end": "02:00",
    }
    assert scheduled_now(item, monday_late)
    assert scheduled_now(item, tuesday_early)
    item["schedule_weekdays"] = [2]
    assert not scheduled_now(item, monday_late)
