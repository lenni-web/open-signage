"""Controller-/Display-Synchronisierung."""

import io
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage.auth import get_setting, set_setting
from open_signage.database import connect, initialize, media_dir
from open_signage.main import app
from open_signage.sync import safe_sync_from_controller, snapshot as sync_snapshot

from helpers import VALID_PNG


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


def test_display_skips_entries_its_version_does_not_support(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    set_setting("device_role", "display")
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("sync_device_token", "device-token")
    controller_data = sync_snapshot()
    controller_data["content"] = [
        {"id": 1, "name": "Bekannt", "kind": "website", "source": "https://example.org", "playlist_id": 1},
        {"id": 2, "name": "Zukunft", "kind": "hologram", "source": "x", "playlist_id": 1},
        {"id": 3, "name": "Ohne Playlist", "kind": "website", "source": "https://example.org", "playlist_id": 99},
    ]
    monkeypatch.setattr("open_signage.sync._request_json", lambda *args, **kwargs: controller_data)
    result = safe_sync_from_controller()
    assert result["status"] == "synchronized"
    assert result["skipped"] == 2
    with connect() as connection:
        assert [row[0] for row in connection.execute("SELECT name FROM content")] == ["Bekannt"]
    assert "2 Einträge" in get_setting("sync_last_warning")
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        device = client.get("/api/system/device").json()
        assert "bitte dieses Display aktualisieren" in device["sync_status"]

    controller_data["content"] = controller_data["content"][:1]
    assert safe_sync_from_controller()["skipped"] == 0
    assert get_setting("sync_last_warning") in (None, "")
