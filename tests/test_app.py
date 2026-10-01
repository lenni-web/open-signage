import sqlite3
import base64
import hashlib
import io
import os
import json
import subprocess
import runpy
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from open_signage.database import initialize
from open_signage.database import connect, integrity_check_if_due, media_dir
from open_signage.application_update import request_update as request_application_update
from open_signage.application_update import update_status as application_update_status
from open_signage.main import app
from open_signage.routes.common import scheduled_now
from open_signage.media_files import file_sha256
from open_signage.display_control import schedule_analysis
from open_signage.media_probe import evaluate_video_probe
from open_signage.system_update import request_update, update_status
from open_signage.version import __version__
from open_signage.upload_security import detect_media_type, ensure_free_space
from open_signage.auth import get_setting, local_player_client, set_setting
from open_signage.sync import safe_sync_from_controller, snapshot as sync_snapshot

PROJECT_ROOT = Path(__file__).parents[1]
VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def legacy_test_initial_password(monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_INITIAL_PASSWORD", "open-signage")
    monkeypatch.setenv("OPEN_SIGNAGE_REQUIRE_INITIAL_PASSWORD_CHANGE", "0")


def test_login_is_rate_limited_per_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        for _ in range(5):
            assert client.post("/api/system/login", json={"password": "falsch"}).status_code == 401
        blocked = client.post("/api/system/login", json={"password": "open-signage"})
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers


def test_initial_password_must_be_changed_before_writes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_SIGNAGE_REQUIRE_INITIAL_PASSWORD_CHANGE", "1")
    with TestClient(app) as client:
        login = client.post("/api/system/login", json={"password": "open-signage"})
        assert login.json()["password_change_required"] is True
        assert client.post(
            "/api/content/website", json={"name": "Gesperrt", "url": "https://example.org"}
        ).status_code == 403
        assert client.post("/api/system/password", json={
            "current_password": "open-signage", "new_password": "wirklich-sicher-123",
        }).status_code == 200
        assert client.post(
            "/api/content/website", json={"name": "Erlaubt", "url": "https://example.org"}
        ).status_code == 201


def test_player_endpoints_require_device_token(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/player/content").status_code == 401
        assert client.get("/api/player/config").status_code == 401
        assert client.post("/api/player/heartbeat", json={"state": "idle"}).status_code == 401
        token = client.get("/api/player/bootstrap").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/player/content", headers=headers).status_code == 200
        assert client.get("/api/player/config", headers=headers).json() == {"transition_ms": 4000}
        assert client.post(
            "/api/player/heartbeat", json={"state": "idle"}, headers=headers
        ).status_code == 204


def test_network_player_can_pair_without_admin_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.post("/api/player/pair", json={"password": "falsch"}).status_code == 401
        paired = client.post("/api/player/pair", json={"password": "open-signage"})
        assert paired.status_code == 200
        token = paired.json()["token"]
        assert token
        assert "open_signage_session" not in paired.cookies
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/player/content", headers=headers).status_code == 200
        assert client.get("/api/player/config", headers=headers).status_code == 200


@pytest.mark.parametrize("address", [
    "10.20.30.40", "172.16.5.10", "172.31.255.250", "192.168.142.192",
    "169.254.10.5", "127.0.0.1", "fd12:3456::10", "fe80::1234", "::1",
])
def test_private_network_clients_are_automatic_players(address: str):
    request = Request({"type": "http", "method": "GET", "path": "/api/player/bootstrap",
                       "headers": [], "client": (address, 12345), "server": ("test", 80),
                       "scheme": "http", "query_string": b""})
    assert local_player_client(request) is True


@pytest.mark.parametrize("address", ["8.8.8.8", "172.32.0.1", "203.0.113.10", "2001:4860:4860::8888"])
def test_public_network_clients_are_not_automatic_players(address: str):
    request = Request({"type": "http", "method": "GET", "path": "/api/player/bootstrap",
                       "headers": [], "client": (address, 12345), "server": ("test", 80),
                       "scheme": "http", "query_string": b""})
    assert local_player_client(request) is False


def test_player_skips_missing_local_media_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        with connect() as connection:
            connection.execute(
                "INSERT INTO content(name, kind, source, position) VALUES (?, 'image', ?, 0)",
                ("Fehlendes Bild", "192.168.142.22.png"),
            )
        token = client.get("/api/player/bootstrap").json()["token"]
        response = client.get(
            "/api/player/content", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    assert response.json() == []


def test_sqlite_busy_timeout_and_integrity_check(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    with connect() as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    result = integrity_check_if_due(timedelta(0))
    assert result["ok"] is True
    assert result["results"] == ["ok"]


def test_upload_detection_uses_content_and_preserves_disk_reserve(tmp_path: Path, monkeypatch):
    image = tmp_path / "angeblich.pdf"
    image.write_bytes(VALID_PNG)
    assert detect_media_type(image) == "image/png"
    monkeypatch.setattr(
        "open_signage.upload_security.shutil.disk_usage",
        lambda _path: shutil._ntuple_diskusage(total=10_000_000_000, used=9_700_000_000, free=300_000_000),
    )
    with pytest.raises(HTTPException) as error:
        ensure_free_space(tmp_path)
    assert error.value.status_code == 507


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


def test_html_pages_version_static_assets_and_disable_document_cache():
    with TestClient(app) as client:
        admin = client.get("/")
        player = client.get("/player")
    assert admin.headers["cache-control"] == "no-store"
    assert player.headers["cache-control"] == "no-store"
    assert f"/static/style.css?v={__version__}" in admin.text
    assert f"/static/admin.js?v={__version__}" in admin.text
    assert f"/static/player.js?v={__version__}" in player.text


def test_raspberry_pi_templates_have_expected_placeholders():
    service = (PROJECT_ROOT / "deploy/open-signage.service").read_text(encoding="utf-8")
    kiosk = (PROJECT_ROOT / "deploy/open-signage-kiosk").read_text(encoding="utf-8")

    assert "@@PORT@@" in service
    assert "Restart=on-failure" in service
    assert "@@PLAYER_URL@@" in kiosk
    assert "@@HEALTH_URL@@" in kiosk
    assert "--autoplay-policy=no-user-gesture-required" in kiosk
    assert "--ozone-platform=wayland" in kiosk
    assert "--user-data-dir" in kiosk
    assert "--disable-crash-reporter" in kiosk
    assert "DBUS_SESSION_BUS_ADDRESS" in kiosk
    assert "--disable-background-networking" in kiosk
    assert "--lang=de-DE" in kiosk
    assert "--accept-lang=de-DE,de" in kiosk
    assert "--disable-translate" in kiosk
    assert "Chromium wurde mit Status" in kiosk

    installer = (PROJECT_ROOT / "scripts/install-raspberry-pi.sh").read_text(
        encoding="utf-8"
    )
    assert "rpd-wayland-core" in installer
    assert "raspi-config nonint do_boot_behaviour B4" in installer
    assert 'KIOSK_USER="signage"' in installer
    assert "ffmpeg" in installer
    assert "--mode MODUS" in installer
    assert "--controller-url URL" in installer
    assert "OPEN_SIGNAGE_MODE" in installer
    assert 'chmod 0755 "${AUTOSTART_FILE}"' in installer
    assert "kiosk.log" in installer
    assert 's|@@KIOSK_USER@@|${KIOSK_USER}|g' in installer
    assert "locale-gen de_DE.UTF-8" in installer
    assert "open-signage-chromium-policy.json" in installer
    assert "open-signage-cursor-guard" in installer
    assert "open-signage-labwc-rc.xml" in installer
    assert "  wtype" in installer

    chromium_policy = json.loads(
        (PROJECT_ROOT / "deploy/open-signage-chromium-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert chromium_policy["TranslateEnabled"] is False

    labwc_config = (
        PROJECT_ROOT / "deploy/open-signage-labwc-rc.xml"
    ).read_text(encoding="utf-8")
    assert '<action name="HideCursor" />' in labwc_config
    assert '<action name="WarpCursor" x="-1" y="-1" />' in labwc_config
    cursor_guard = (
        PROJECT_ROOT / "deploy/open-signage-cursor-guard"
    ).read_text(encoding="utf-8")
    assert "while sleep 2" in cursor_guard
    assert 'output_states="$(wlopm 2>/dev/null)"' in cursor_guard
    assert "return 0" in cursor_guard
    assert "wtype -M alt -M logo -k h" in cursor_guard

    player_style = (
        PROJECT_ROOT / "src/open_signage/static/style.css"
    ).read_text(encoding="utf-8")
    assert ".player *" in player_style
    assert "cursor: none !important" in player_style
    assert ".player-transition-source.player-leaving" in player_style
    assert ".content-image" in player_style
    assert "isolation: isolate" in player_style
    assert "backface-visibility: hidden" in player_style
    player_script = (
        PROJECT_ROOT / "src/open_signage/static/player.js"
    ).read_text(encoding="utf-8")
    assert "function transitionTo(" in player_script
    assert "previousElements.forEach" in player_script
    assert "let transitionMs = 4000" in player_script
    assert 'fetch("/api/player/config"' in player_script
    assert 'fetch("/api/player/pair"' in player_script
    assert "PLAYER_TOKEN_KEY" in player_script
    assert "const WEBSITE_SETTLE_MS = 4000" in player_script
    assert "function settleAfter(" in player_script
    assert "function waitForVideoFrame(" in player_script
    assert "requestVideoFrameCallback" in player_script
    assert 'layer.className = "player-layer"' in player_script
    assert 'classList.add("player-transition-source")' in player_script
    assert 'classList.add("player-leaving")' in player_script


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
    monkeypatch.setattr("open_signage.routes.content.validate_video", lambda _path: compatibility)

    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/upload",
            data={"duration_seconds": "10", "muted": "false", "play_to_end": "true"},
            files={"file": ("video.mp4", b"\x00\x00\x00\x18ftypisom0000", "video/mp4")},
        )

    assert response.status_code == 201
    assert response.json()["kind"] == "video"
    assert response.json()["muted"] is False
    assert response.json()["play_to_end"] is True
    assert response.json()["media_id"] is not None
    assert response.json()["compatibility"] == compatibility
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        library = client.get("/api/media-library").json()
    assert len(library) == 1
    assert library[0]["id"] == response.json()["media_id"]
    assert library[0]["name"] == "video.mp4"


def test_direct_image_upload_is_added_to_media_library(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/upload",
            files={"file": ("foto.png", VALID_PNG, "image/png")},
        )
        assert response.status_code == 201
        content = response.json()
        library = client.get("/api/media-library").json()

    assert content["kind"] == "image"
    assert content["media_id"] == library[0]["id"]
    assert content["source"] == library[0]["source"]
    assert library[0]["original_source"].endswith(".png")
    assert library[0]["thumbnail_source"].endswith("-thumb.jpg")


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
    assert "cec-utils locales wlr-randr wlopm wtype" in application_script
    assert '@@KIOSK_USER@@|${KIOSK_USER}' in application_script
    assert "cec-utils" in installer
    assert "open-signage-display-control.path" in installer
    assert "open-signage-display-schedule.timer" in installer
    assert "  wlopm" in installer
    display_helper = (PROJECT_ROOT / "deploy/open-signage-display-control").read_text(encoding="utf-8")
    assert "cec-client" in display_helper
    assert "wlopm" in display_helper
    assert "wlr-randr" in display_helper
    assert "vcgencmd" not in display_helper
    assert "@@KIOSK_USER@@" in display_helper
    assert "sudo" not in display_helper


def test_admin_contains_system_navigation_and_update_controls():
    admin = (PROJECT_ROOT / "src/open_signage/static/admin.html").read_text(
        encoding="utf-8"
    )

    assert 'data-page="system-page"' in admin
    assert 'data-page="settings-page"' in admin
    assert 'id="settings-content"' in admin
    assert '<h2 class="page-title">System</h2>' in admin
    assert 'id="wlan-info"' in admin
    assert 'id="ethernet-info"' in admin
    assert 'class="network-overview"' in admin
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
    assert 'id="playlist-select"' in admin
    assert 'id="playlist-create"' in admin
    assert 'id="library-search"' in admin
    assert 'id="library-bulk-add"' in admin
    assert 'id="monitoring-summary"' in admin
    assert 'id="monitoring-refresh"' in admin
    assert 'id="display-control-form"' in admin
    assert 'name="resolution_mode"' in admin
    assert 'id="display-resolution-status"' in admin
    assert 'name="transition_ms"' in admin
    player_html = (PROJECT_ROOT / "src/open_signage/static/player.html").read_text(encoding="utf-8")
    assert 'id="player-pair-form"' in player_html
    assert 'name="password"' in player_html

    admin_script = (
        PROJECT_ROOT / "src/open_signage/static/admin.js"
    ).read_text(encoding="utf-8")
    assert "function organizeAdministrationPages()" in admin_script
    assert "async function openSettingsPage()" in admin_script
    assert 'id="admin-clock"' in admin
    assert 'data-display-action="on"' in admin
    assert 'data-display-action="off"' in admin
    assert 'id="add-content-type"' in admin
    assert 'video/mp4,video/webm' in admin
    admin_js = (PROJECT_ROOT / "src/open_signage/static/admin.js").read_text(encoding="utf-8")
    assert "preview.poster = item.thumbnail_source" in admin_js
    assert "Optimal konvertieren" in admin_js
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


def test_unauthenticated_session_status_is_not_an_http_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/system/session")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False}


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
                "text_align": "center",
                "vertical_position": "bottom",
                "text_color": "#eeeeee",
                "accent_color": "#ffcc00",
                "font_size": "large",
                "font_family": "serif",
                "background_dim": "35",
                "focus_x": "25",
                "focus_y": "70",
                "template_style": "elegant",
                "duration_seconds": "12",
            },
            files={
                "background": ("foyer.png", VALID_PNG, "image/png"),
                "logo": ("logo.png", VALID_PNG, "image/png"),
            },
        )
        assert created.status_code == 201
        item = created.json()
        assert item["kind"] == "text"
        assert item["text_config"]["headline"] == "Willkommen"
        assert item["text_config"]["shadow_box"] is True
        assert item["text_config"]["shadow_intensity"] == "dark"
        assert item["text_config"]["text_align"] == "center"
        assert item["text_config"]["vertical_position"] == "bottom"
        assert item["text_config"]["background_dim"] == 35
        assert item["text_config"]["focus_x"] == 25
        logo = tmp_path / "media" / Path(item["text_config"]["logo_source"]).name
        assert logo.exists()
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
        assert edited.json()["text_config"]["logo_source"] == item["text_config"]["logo_source"]

        assert client.delete(f"/api/content/{item['id']}").status_code == 204
        assert not old_background.exists()
        assert not logo.exists()


def test_text_content_requires_background_and_some_text(tmp_path: Path, monkeypatch):
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


def test_text_content_supports_video_background(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "open_signage.routes.content.validate_video",
        lambda _path: {"checked": True, "video_codecs": ["h264"]},
    )
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post(
            "/api/content/text",
            data={"name": "Video-Hinweis", "headline": "Willkommen"},
            files={"background": ("loop.mp4", b"\x00\x00\x00\x18ftypisom0000", "video/mp4")},
        )
        assert created.status_code == 201
        item = created.json()
        assert item["text_config"]["background_kind"] == "video"
        assert item["source"].endswith(".mp4")
        assert (tmp_path / "media" / Path(item["source"]).name).exists()


def test_media_library_reuses_files_for_playlist_and_text(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/media-library",
            files={"file": ("hintergrund.png", VALID_PNG, "image/png")},
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


def test_library_image_is_optimized_and_can_be_edited(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/media-library",
            files={"file": ("foto.png", VALID_PNG, "image/png")},
        )
        assert uploaded.status_code == 201
        media = uploaded.json()
        assert media["original_source"].endswith(".png")
        assert media["source"].endswith("-display.jpg")
        assert media["thumbnail_source"].endswith("-thumb.jpg")
        original = tmp_path / "media" / Path(media["original_source"]).name
        old_display = tmp_path / "media" / Path(media["source"]).name
        assert original.exists() and old_display.exists()

        edited = client.post(
            f"/api/media-library/{media['id']}/edit-image",
            json={
                "rotate": 90, "crop_16_9": True, "focus_x": 25, "focus_y": 75,
                "brightness": 1.1, "contrast": 1.2,
            },
        )
        assert edited.status_code == 200
        result = edited.json()
        assert result["source"] != media["source"]
        assert original.exists()
        assert not old_display.exists()


def test_library_metadata_rename_category_and_bulk_playlist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        ids = []
        for name in ("eins.png", "zwei.png"):
            uploaded = client.post(
                "/api/media-library", files={"file": (name, VALID_PNG, "image/png")}
            )
            ids.append(uploaded.json()["id"])
        updated = client.patch(
            f"/api/media-library/{ids[0]}", json={"name": "Bühne", "category": "Veranstaltung"}
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Bühne"
        assert updated.json()["category"] == "Veranstaltung"

        bulk = client.post(
            "/api/media-library/bulk-playlist",
            json={"media_ids": ids, "duration_seconds": 17},
        )
        assert bulk.status_code == 201
        assert len(bulk.json()["created_ids"]) == 2
        assert {item["duration_seconds"] for item in client.get("/api/content").json()} == {17}
        assert all(item["usage_count"] == 1 for item in client.get("/api/media-library").json())


def test_library_video_gets_thumbnail_and_can_be_transcoded(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    video = tmp_path / "input.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=blue:s=320x180:d=0.2", "-c:v", "mpeg4", str(video)],
        check=True,
    )
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/media-library",
            files={"file": ("clip.mp4", video.read_bytes(), "video/mp4")},
        )
        assert uploaded.status_code == 201
        media = uploaded.json()
        playlist = client.post(
            f"/api/media-library/{media['id']}/playlist",
            json={"duration_seconds": 12, "muted": False, "play_to_end": True},
        )
        assert playlist.status_code == 201
        assert playlist.json()["muted"] is False
        assert playlist.json()["play_to_end"] is True
        text = client.post(
            "/api/content/text",
            data={"name": "Video-Text", "headline": "Live", "library_media_id": str(media["id"])},
        )
        assert text.status_code == 201
        assert text.json()["text_config"]["background_kind"] == "video"
        assert text.json()["media_id"] == media["id"]
        assert media["thumbnail_source"].endswith("-video-thumb.jpg")
        assert media["metadata"]["width"] == 320
        converted = client.post(f"/api/media-library/{media['id']}/transcode")
        assert converted.status_code == 202
        for _ in range(100):
            job = client.get(f"/api/conversions/{converted.json()['job_id']}").json()
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert job["status"] == "completed", job
        converted_media = job["media"]
        assert converted_media["source"].endswith("-converted.mp4")
        assert converted_media["metadata"]["video_codec"] == "h264"
        first_converted = tmp_path / "media" / Path(converted_media["source"]).name
        assert first_converted.exists()
        converted_again = client.post(f"/api/media-library/{media['id']}/transcode")
        assert converted_again.status_code == 202
        for _ in range(100):
            second_job = client.get(f"/api/conversions/{converted_again.json()['job_id']}").json()
            if second_job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert second_job["status"] == "completed", second_job
        assert second_job["media"]["source"] != converted_media["source"]
        assert not first_converted.exists()


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


def test_multiple_playlists_are_isolated_and_switch_player(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        first = client.post(
            "/api/content/website", json={"name": "Standardinhalt", "url": "https://one.example"}
        ).json()
        default_playlist = next(item for item in client.get("/api/playlists").json() if item["active"])

        second_playlist = client.post("/api/playlists", json={"name": "Abend"})
        assert second_playlist.status_code == 201
        second_id = second_playlist.json()["id"]
        client.post(f"/api/playlists/{second_id}/activate")
        assert client.get("/api/content").json() == []
        second = client.post(
            "/api/content/website", json={"name": "Abendinhalt", "url": "https://two.example"}
        ).json()
        assert [item["id"] for item in client.get("/api/player/content").json()] == [second["id"]]
        assert client.delete(f"/api/playlists/{second_id}").status_code == 409

        client.post(f"/api/playlists/{default_playlist['id']}/activate")
        assert [item["id"] for item in client.get("/api/player/content").json()] == [first["id"]]
        assert client.delete(f"/api/playlists/{second_id}").status_code == 204
        assert len(client.get("/api/playlists").json()) == 1


def test_player_heartbeat_and_monitoring(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        token = client.get("/api/player/bootstrap").json()["token"]
        heartbeat = client.post(
            "/api/player/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "state": "playing", "content_id": 42,
                "content_name": "Begrüßung", "error": None,
            },
        )
        assert heartbeat.status_code == 204
        client.post(
            "/api/player/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "state": "error", "content_id": 42,
                "content_name": "Begrüßung", "error": "Bild konnte nicht geladen werden.",
            },
        )
        assert client.get("/api/system/monitoring").status_code == 401
        client.post("/api/system/login", json={"password": "open-signage"})
        monitoring = client.get("/api/system/monitoring")
        assert monitoring.status_code == 200
        status = monitoring.json()
        assert status["player"]["online"] is True
        assert status["player"]["content_name"] == "Begrüßung"
        assert status["events"][0]["message"] == "Bild konnte nicht geladen werden."
        assert status["version"] == __version__
        assert set(status) >= {"disk", "temperature_celsius", "warnings", "system_update", "application_update"}


def test_player_heartbeat_rejects_unknown_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        token = client.get("/api/player/bootstrap").json()["token"]
        assert client.post(
            "/api/player/heartbeat", json={"state": "compromised"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 422


def test_playlist_schedule_can_override_manual_playlist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        client.post("/api/content/website", json={"name": "Standard", "url": "https://example.org", "duration_seconds": 12})
        scheduled = client.post("/api/playlists", json={"name": "Abend"}).json()
        client.post(f"/api/playlists/{scheduled['id']}/activate")
        special = client.post("/api/content/website", json={"name": "Geplant", "url": "https://example.net", "duration_seconds": 12}).json()
        client.post("/api/playlists/1/activate")
        response = client.patch(f"/api/playlists/{scheduled['id']}/schedule", json={
            "schedule_enabled": True, "schedule_weekdays": [datetime.now().astimezone().weekday()],
            "schedule_daily_start": "00:00", "schedule_daily_end": "23:59",
        })
        assert response.status_code == 200
        shown = client.get("/api/player/content").json()
    assert [item["id"] for item in shown] == [special["id"]]


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


def test_device_role_and_system_action_are_persisted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        first = client.get("/api/system/device").json()
        assert first["role"] == "standalone"
        updated = client.patch("/api/system/device", json={"role": "display", "controller_url": "http://controller.local:8080", "current_password": "open-signage"})
        assert updated.status_code == 200
        assert updated.json()["device_id"] == first["device_id"]
        assert client.post("/api/system/action", json={"action": "reboot"}).status_code == 202
    assert (tmp_path / "system-action-request").read_text() == "reboot"


def test_installer_environment_initializes_display_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_SIGNAGE_MODE", "display")
    monkeypatch.setenv("OPEN_SIGNAGE_CONTROLLER_URL", "http://controller.local:8080")
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        device = client.get("/api/system/device").json()
    assert device["role"] == "display"
    assert device["controller_url"] == "http://controller.local:8080"


@pytest.mark.parametrize(("legacy", "expected"), [("master", "controller"), ("slave", "display")])
def test_legacy_device_roles_are_migrated(tmp_path: Path, monkeypatch, legacy: str, expected: str):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize(); set_setting("device_role", legacy)
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        assert client.get("/api/system/device").json()["role"] == expected
    assert get_setting("device_role") == expected


def test_display_mode_blocks_central_writes_but_allows_mode_change(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        assert client.patch("/api/system/device", json={
            "role": "display", "controller_url": "http://controller.local:8080",
            "current_password": "falsch",
        }).status_code == 400
        changed = client.patch("/api/system/device", json={
            "role": "display", "controller_url": "http://controller.local:8080",
            "current_password": "open-signage",
        })
        assert changed.status_code == 200
        assert client.get("/api/system/session").json()["device_mode"] == "display"
        blocked = client.post("/api/content/website", json={
            "name": "Lokal verboten", "url": "https://example.org",
        })
        assert blocked.status_code == 403
        assert "Controller" in blocked.json()["detail"]
        assert client.patch("/api/system/display-control", json={}).status_code == 403
        assert client.post("/api/system/display-control/action", json={"action": "status"}).status_code == 202
        assert client.patch("/api/system/device", json={
            "role": "standalone", "controller_url": "",
            "current_password": "open-signage",
        }).status_code == 200
        assert client.post("/api/content/website", json={
            "name": "Lokal erlaubt", "url": "https://example.org",
        }).status_code == 201


def test_display_control_configuration_and_request_are_protected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/system/display-control").status_code == 401
        client.post("/api/system/login", json={"password": "open-signage"})
        initial = client.get("/api/system/display-control").json()
        assert initial["config"]["cec_address"] == "0"
        assert initial["config"]["resolution_mode"] == "1080p60"
        updated = client.patch("/api/system/display-control", json={
            "cec_address": "A", "activate_source": True, "fallback_hdmi_signal": True,
            "resolution_mode": "720p60",
            "transition_ms": 2300,
            "schedule_enabled": True, "schedule_entries": [
                {"weekday": 1, "on": "08:00", "off": "09:00"},
                {"weekday": 1, "on": "19:30", "off": "21:30"},
                {"weekday": 3, "on": "09:00", "off": "12:00"},
                {"weekday": 6, "on": "10:15", "off": "13:30"},
            ],
        })
        assert updated.status_code == 200
        assert len(updated.json()["config"]["schedule_entries"]) == 4
        assert updated.json()["config"]["resolution_mode"] == "720p60"
        assert updated.json()["config"]["transition_ms"] == 2300
        assert [entry["weekday"] for entry in updated.json()["config"]["schedule_entries"][:2]] == [1, 1]
        assert client.post("/api/system/display-control/action", json={"action": "on"}).status_code == 202
        assert client.post("/api/system/display-control/action", json={"action": "arbitrary"}).status_code == 422
    assert (tmp_path / "display-control-request").read_text() == "on"


def test_invalid_display_resolution_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.patch("/api/system/display-control", json={
            "resolution_mode": "3840x2160; reboot",
        })
    assert response.status_code == 422


def test_transition_duration_is_limited_server_side(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        too_short = client.patch("/api/system/display-control", json={"transition_ms": 999})
        too_long = client.patch("/api/system/display-control", json={"transition_ms": 6001})
    assert too_short.status_code == 422
    assert too_long.status_code == 422


def test_display_schedule_handles_daytime_and_overnight_windows():
    helper = runpy.run_path(str(PROJECT_ROOT / "deploy/open-signage-display-control"))
    scheduled_state = helper["scheduled_state"]
    daytime = {"schedule_enabled": True, "schedule_entries": [
        {"weekday": 1, "on": "08:00", "off": "09:00"},
        {"weekday": 1, "on": "19:30", "off": "21:30"},
        {"weekday": 3, "on": "09:00", "off": "12:00"},
        {"weekday": 6, "on": "10:15", "off": "13:30"},
    ]}
    assert scheduled_state(daytime, datetime(2026, 8, 9, 11, 0)) == "on"  # Sunday
    assert scheduled_state(daytime, datetime(2026, 8, 11, 20, 0)) == "on"  # Tuesday
    assert scheduled_state(daytime, datetime(2026, 8, 11, 8, 30)) == "on"  # second Tuesday window
    assert scheduled_state(daytime, datetime(2026, 8, 11, 12, 0)) == "off"
    assert scheduled_state(daytime, datetime(2026, 8, 13, 10, 0)) == "on"  # Thursday
    assert scheduled_state(daytime, datetime(2026, 8, 10, 20, 0)) == "off"
    overnight = {"schedule_enabled": True, "schedule_entries": [{"weekday": 0, "on": "22:00", "off": "02:00"}]}
    assert scheduled_state(overnight, datetime(2026, 8, 10, 23, 0)) == "on"
    assert scheduled_state(overnight, datetime(2026, 8, 11, 1, 0)) == "on"
    assert scheduled_state(overnight, datetime(2026, 8, 11, 3, 0)) == "off"


def test_display_schedule_applies_resolution_and_reasserts_off(tmp_path: Path):
    helper = runpy.run_path(str(PROJECT_ROOT / "deploy/open-signage-display-control"))
    globals_ = helper["main"].__globals__
    request_path = tmp_path / "display-control-request"
    status_path = tmp_path / "display-control-status.json"
    globals_["REQUEST"] = request_path
    globals_["STATUS"] = status_path
    globals_["sanitized_config"] = lambda: {
        "schedule_enabled": True,
        "schedule_entries": [{"weekday": 0, "on": "00:00", "off": "23:59"}],
    }
    actions = []
    globals_["execute"] = lambda action, _config: actions.append(action)
    globals_["scheduled_state"] = lambda _config, _now: "on"
    status_path.write_text(json.dumps({"desired_state": "on"}))
    old_argv = sys.argv
    try:
        sys.argv = [old_argv[0], "--schedule"]
        assert helper["main"]() == 0
        assert actions == ["resolution"]
        actions.clear()
        globals_["scheduled_state"] = lambda _config, _now: "off"
        status_path.write_text(json.dumps({"desired_state": "off"}))
        assert helper["main"]() == 0
        assert actions == ["off"]
    finally:
        sys.argv = old_argv


def test_legacy_display_schedule_is_migrated_on_read(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "display-control.json").write_text(json.dumps({
        "schedule_enabled": True, "schedule_weekdays": [1, 3],
        "schedule_on": "09:00", "schedule_off": "12:00",
    }))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        config = client.get("/api/system/display-control").json()["config"]
    assert config["schedule_entries"] == [
        {"weekday": 1, "on": "09:00", "off": "12:00"},
        {"weekday": 3, "on": "09:00", "off": "12:00"},
    ]


def test_null_display_schedule_entries_are_normalized(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "display-control.json").write_text(
        json.dumps({"schedule_enabled": False, "schedule_entries": None})
    )
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        config = client.get("/api/system/display-control").json()["config"]
    assert config["schedule_entries"] == []


def test_privileged_display_helper_sanitizes_its_configuration(tmp_path: Path):
    helper = runpy.run_path(str(PROJECT_ROOT / "deploy/open-signage-display-control"))
    config_path = tmp_path / "display-control.json"
    config_path.write_text(json.dumps({
        "cec_address": "0\nstandby 0", "schedule_enabled": True,
        "resolution_mode": "../../bin/sh",
        "schedule_entries": [
            {"weekday": 1, "on": "19:30", "off": "21:30"},
            {"weekday": 1, "on": "08:00", "off": "09:00"},
            {"weekday": 99, "on": "08:00", "off": "12:00"},
            {"weekday": 2, "on": "invalid", "off": "21:30"},
        ], "activate_source": "yes",
    }))
    helper["sanitized_config"].__globals__["CONFIG"] = config_path
    config = helper["sanitized_config"]()
    assert config["cec_address"] == "0"
    assert config["schedule_entries"] == [
        {"weekday": 1, "on": "08:00", "off": "09:00"},
        {"weekday": 1, "on": "19:30", "off": "21:30"},
    ]
    assert config["activate_source"] is False
    assert config["resolution_mode"] == "1080p60"
    assert config["transition_ms"] == 4000


def test_cec_transmit_error_is_failure_even_with_zero_exit_status(monkeypatch):
    helper = runpy.run_path(str(PROJECT_ROOT / "deploy/open-signage-display-control"))
    monkeypatch.setattr(helper["cec"].__globals__["shutil"], "which", lambda _name: "/usr/bin/cec-client")
    helper["cec"].__globals__["run"] = lambda _command, _input: subprocess.CompletedProcess(
        args=[], returncode=0, stdout="opening a connection to the CEC adapter...\n",
        stderr="ERROR: ioctl CEC_TRANSMIT failed - tx_status=00 errno=64",
    )
    ok, output = helper["cec"]("standby 0")
    assert ok is False
    assert "CEC_TRANSMIT failed" in output


def test_display_action_uses_hdmi_fallback_after_cec_failure(monkeypatch):
    helper = runpy.run_path(str(PROJECT_ROOT / "deploy/open-signage-display-control"))
    captured = {}
    helper["execute"].__globals__["cec_adapter"] = lambda _address: (None, "Kein CEC-Display")
    helper["execute"].__globals__["wayland_signal"] = lambda on: (
        True, "HDMI-A-2 wurde deaktiviert." if on is False else "HDMI-A-2 on", "HDMI-A-2"
    )
    helper["execute"].__globals__["write_status"] = lambda **values: captured.update(values)
    helper["execute"]("off", {"cec_address": "0", "fallback_hdmi_signal": True})
    assert captured["method"] == "wayland_dpms"
    assert captured["output_name"] == "HDMI-A-2"
    assert captured["power_status"] == "off"
    assert "Fallback ausgeführt" in captured["message"]


def test_display_action_uses_fallback_when_cec_does_not_change_power_state():
    helper = runpy.run_path(str(PROJECT_ROOT / "deploy/open-signage-display-control"))
    captured = {}
    globals_ = helper["execute"].__globals__
    globals_["cec_adapter"] = lambda _address: ("/dev/cec0", "power status: on")
    globals_["cec"] = lambda _command, _device=None, **_kwargs: (
        True, "opening a connection to the CEC adapter..."
    )
    globals_["cec_power_state"] = lambda _address, _device: ("on", "power status: on")
    globals_["time"].sleep = lambda _seconds: None
    globals_["wayland_signal"] = lambda on: (
        True, "HDMI-A-2 wurde deaktiviert." if on is False else "HDMI-A-2 on", "HDMI-A-2"
    )
    globals_["write_status"] = lambda **values: captured.update(values)

    helper["execute"]("off", {
        "cec_address": "0", "activate_source": False, "fallback_hdmi_signal": True,
    })

    assert captured["method"] == "wayland_dpms"
    assert captured["power_status"] == "off"
    assert "statt 'off'" in captured["message"]
    assert "Fallback ausgeführt" in captured["message"]


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


def test_schedule_analysis_detects_overlap_and_next_action():
    now = datetime(2026, 8, 11, 7, 0).astimezone()
    result = schedule_analysis({"schedule_entries": [
        {"weekday": 1, "on": "08:00", "off": "10:00"},
        {"weekday": 1, "on": "09:00", "off": "11:00"},
    ]}, now)
    assert result["conflicts"] == [{"first": 0, "second": 1}]
    assert result["next_action"]["action"] == "on"


def test_controller_registers_display_and_protects_snapshot(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        client.patch("/api/system/device", json={"role": "controller", "controller_url": "", "current_password": "open-signage"})
        pairing = client.get("/api/system/device").json()["pairing_code"]
        assert client.get("/api/sync/snapshot").status_code == 401
        registration = client.post("/api/sync/register", json={
            "device_id": "slave-1", "name": "Foyer", "pairing_token": pairing,
        })
        assert registration.status_code == 200
        token = registration.json()["device_token"]
        snapshot = client.get("/api/sync/snapshot", headers={"Authorization": f"Bearer {token}"})
        assert snapshot.status_code == 200
        assert snapshot.json()["format"] == 1
        devices = client.get("/api/system/device").json()["registered_devices"]
        assert devices[0]["device_id"] == "slave-1"


def test_display_applies_snapshot_and_keeps_device_specific_settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    set_setting("device_id", "local-display")
    set_setting("device_role", "display")
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("sync_pairing_code", "pair-me")
    master_data = sync_snapshot()
    master_data["settings"]["screen_name"] = "Vom Master"
    master_data["playlists"][0]["name"] = "Master-Playlist"

    def fake_request(url, method="GET", data=None, token=""):
        return {"device_token": "individual-device-token"} if url.endswith("/register") else master_data

    monkeypatch.setattr("open_signage.sync._request_json", fake_request)
    result = safe_sync_from_controller()
    assert result["status"] == "synchronized"
    assert get_setting("screen_name") == "Vom Master"
    assert get_setting("device_id") == "local-display"
    assert get_setting("device_role") == "display"
    assert get_setting("sync_device_token") == "individual-device-token"
    with connect() as connection:
        assert connection.execute("SELECT name FROM playlists WHERE id = 1").fetchone()[0] == "Master-Playlist"


VALID_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"


def create_non_library_media(client) -> tuple[dict, dict]:
    pdf = client.post(
        "/api/content/upload", files={"file": ("plan.pdf", VALID_PDF, "application/pdf")}
    ).json()
    text = client.post(
        "/api/content/text",
        data={"name": "Hinweis", "headline": "Willkommen"},
        files={
            "background": ("foyer.png", VALID_PNG, "image/png"),
            "logo": ("logo.png", VALID_PNG, "image/png"),
        },
    ).json()
    return pdf, text


def test_pdfs_text_backgrounds_and_logos_are_synced_and_not_orphans(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        pdf, text = create_non_library_media(client)
        (tmp_path / "media" / "orphan.bin").write_bytes(b"orphan")
        expected = {
            Path(pdf["source"]).name,
            Path(text["source"]).name,
            Path(text["text_config"]["logo_source"]).name,
        }
        assert expected.issubset(sync_snapshot()["files"])
        assert "orphan.bin" not in sync_snapshot()["files"]
        assert client.get("/api/system/storage").json()["orphan_file_count"] == 1
        assert client.post("/api/system/storage/orphans/cleanup").json()["removed_files"] == 1
        assert all((tmp_path / "media" / name).is_file() for name in expected)


def test_display_sync_downloads_media_ignores_unknown_columns_and_removes_stale_files(
    tmp_path: Path, monkeypatch
):
    controller_dir = tmp_path / "controller"
    display_dir = tmp_path / "display"
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(controller_dir))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        pdf, text = create_non_library_media(client)
        controller_data = sync_snapshot()
    for row in controller_data["content"]:
        row["future_column"] = "aus einer neueren Version"

    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(display_dir))
    initialize()
    set_setting("device_id", "local-display")
    set_setting("device_role", "display")
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("sync_device_token", "device-token")
    stale = media_dir() / "stale.png"
    stale.write_bytes(VALID_PNG)
    downloads = []

    def fake_urlopen(request, timeout=0):
        filename = request.full_url.rsplit("/", 1)[-1]
        downloads.append(filename)
        return io.BytesIO((controller_dir / "media" / filename).read_bytes())

    monkeypatch.setattr("open_signage.sync._request_json", lambda *args, **kwargs: controller_data)
    monkeypatch.setattr("open_signage.sync.urllib.request.urlopen", fake_urlopen)
    result = safe_sync_from_controller()
    assert result["status"] == "synchronized", result
    assert result["removed_files"] == 1
    assert not stale.exists()
    assert sorted(downloads) == sorted(controller_data["files"])
    for name in controller_data["files"]:
        assert (display_dir / "media" / name).read_bytes() == (controller_dir / "media" / name).read_bytes()
    with connect() as connection:
        assert {row[0] for row in connection.execute("SELECT id FROM content")} == {pdf["id"], text["id"]}

    downloads.clear()
    assert safe_sync_from_controller()["status"] == "synchronized"
    assert downloads == []


def test_cached_file_hash_is_invalidated_when_file_changes(tmp_path: Path):
    path = tmp_path / "datei.bin"
    path.write_bytes(b"erste")
    first = file_sha256(path)
    path.write_bytes(b"zweit")
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert file_sha256(path) != first
    assert file_sha256(path) == hashlib.sha256(b"zweit").hexdigest()
