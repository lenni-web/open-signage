"""Controller-Funktionen für Displays: feste Playlist, Sofortmeldung und Bildschirmfotos."""

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage import live, sync
from open_signage.announcement import local_announcement, player_announcement, set_announcement
from open_signage.auth import set_setting
from open_signage.database import data_dir, initialize
from open_signage.main import app

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _controller_with_display(client) -> dict:
    client.post("/api/system/login", json={"password": "open-signage"})
    client.patch("/api/system/device", json={"role": "controller", "controller_url": "", "current_password": "open-signage"})
    pairing = client.get("/api/system/device").json()["pairing_code"]
    token = client.post("/api/sync/register", json={
        "device_id": "foyer-pi", "name": "Foyer", "pairing_token": pairing}).json()["device_token"]
    return {"Authorization": f"Bearer {token}"}


def test_display_gets_fixed_playlist_without_playlist_schedules(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        headers = _controller_with_display(client)
        termine = client.post("/api/playlists", json={"name": "Termine"}).json()
        gottesdienst = client.post("/api/playlists", json={"name": "Gottesdienst"}).json()
        client.patch(f"/api/playlists/{gottesdienst['id']}/schedule", json={"schedule_enabled": True})

        def active(snapshot):
            return {item["name"]: (item["active"], item["schedule_enabled"]) for item in snapshot["playlists"]}

        assert active(client.get("/api/sync/snapshot", headers=headers).json())["Standard"] == (1, 0)
        assert client.put("/api/system/displays/foyer-pi/playlist", json={"playlist_id": 999}).status_code == 404
        assert client.put("/api/system/displays/unbekannt/playlist", json={"playlist_id": termine["id"]}).status_code == 404
        assert client.put("/api/system/displays/foyer-pi/playlist", json={"playlist_id": termine["id"]}).status_code == 200
        assigned = active(client.get("/api/sync/snapshot", headers=headers).json())
        assert assigned == {"Standard": (0, 0), "Termine": (1, 0), "Gottesdienst": (0, 0)}
        overview = client.get("/api/system/displays").json()
        assert overview["displays"][0]["playlist_id"] == termine["id"]
        assert {item["name"] for item in overview["playlists"]} == {"Standard", "Termine", "Gottesdienst"}
        # Controller selbst bleibt unverändert.
        assert {item["name"]: item["schedule_enabled"] for item in client.get("/api/playlists").json()}["Gottesdienst"]

        assert client.delete(f"/api/playlists/{termine['id']}").status_code == 204
        assert client.get("/api/system/displays").json()["displays"][0]["playlist_id"] is None
        assert active(client.get("/api/sync/snapshot", headers=headers).json())["Gottesdienst"] == (0, 1)


def test_announcement_reaches_players_and_displays(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        headers = _controller_with_display(client)
        assert client.put("/api/announcement", json={"text": "   "}).status_code == 422
        assert client.put("/api/announcement", json={"text": "x", "style": "blinkend"}).status_code == 422
        bottom = client.put("/api/announcement", json={"text": "Unten", "style": "bottom", "minutes": 1}).json()
        assert bottom["announcement"]["style"] == "bottom"
        created = client.put("/api/announcement", json={
            "text": "Gottesdienst beginnt um 10:30 Uhr", "style": "fullscreen", "minutes": 15}).json()["announcement"]
        assert created["style"] == "fullscreen" and created["until"]
        assert client.get("/api/player/config").json()["announcement"]["text"] == "Gottesdienst beginnt um 10:30 Uhr"
        shared = client.get("/api/sync/live", headers=headers).json()["announcement"]
        assert shared["text"] == "Gottesdienst beginnt um 10:30 Uhr"
        assert client.delete("/api/announcement").json() == {"announcement": None}
        assert client.get("/api/player/config").json()["announcement"] is None
        endless = client.put("/api/announcement", json={"text": "Bitte Handys aus", "minutes": None}).json()
        assert endless["announcement"]["until"] is None and endless["announcement"]["style"] == "top"

    set_announcement("Kurz", "bottom", 1)
    assert local_announcement(datetime.now(UTC) + timedelta(minutes=2)) is None


def test_display_shows_announcement_from_controller(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    set_setting("device_role", "display")
    monkeypatch.setattr(live, "_controller_state", lambda: {
        "announcement": live._clean_announcement({"text": "Hallo", "style": "seltsam", "until": 5})})
    assert player_announcement() == {"text": "Hallo", "style": "top", "until": None, "created_at": None}
    assert live._clean_announcement({"text": " "}) is None and live._clean_announcement("x") is None


def test_screenshots_are_requested_only_while_overview_is_open(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        headers = _controller_with_display(client)
        assert client.get("/api/sync/commands", headers=headers).json()["screenshot"] is False
        assert client.get("/api/system/displays/foyer-pi/screenshot").status_code == 404
        assert client.get("/api/system/displays").json()["displays"][0]["screenshot_at"] is None
        assert client.get("/api/sync/commands", headers=headers).json()["screenshot"] is True

        assert client.post("/api/sync/screenshot", content=JPEG).status_code == 401
        assert client.post("/api/sync/screenshot", content=b"<html>", headers=headers).status_code == 415
        assert client.post("/api/sync/screenshot", content=b"\xff\xd8\xff" + b"0" * (1024 * 1024),
                           headers=headers).status_code == 413
        assert client.post("/api/sync/screenshot", content=JPEG, headers=headers).status_code == 204
        display = client.get("/api/system/displays").json()["displays"][0]
        assert display["screenshot_at"]
        image = client.get("/api/system/displays/foyer-pi/screenshot")
        assert image.content == JPEG and image.headers["content-type"] == "image/jpeg"

        set_setting("screenshots_wanted_until", (datetime.now(UTC) - timedelta(seconds=1)).isoformat())
        assert client.get("/api/sync/commands", headers=headers).json()["screenshot"] is False

        assert client.delete("/api/system/displays/foyer-pi").status_code == 204
        assert client.delete("/api/system/displays/foyer-pi").status_code == 404
        assert client.get("/api/system/displays/foyer-pi/screenshot").status_code == 404
        assert client.get("/api/sync/commands", headers=headers).status_code == 401


def test_display_uploads_new_screenshots_and_requests_the_next(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sync, "SCREENSHOT_HELPER", helper)
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("sync_device_token", "device-token")
    uploads = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"command": null, "screenshot": true}'

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/sync/screenshot"):
            uploads.append(request.data)
        return Response()

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)
    request_file = data_dir() / "screenshot-request"
    assert sync.poll_controller_command() is None
    assert request_file.exists() and uploads == []

    request_file.unlink()
    (data_dir() / "screenshot.jpg").write_bytes(JPEG)
    sync.poll_controller_command()
    assert uploads == [JPEG]
    assert not request_file.exists()  # das Foto ist frisch, das nächste folgt frühestens nach 10 Sekunden
    sync.poll_controller_command()
    assert uploads == [JPEG]  # unverändertes Foto wird nicht erneut gesendet

    old = time.time() - 60
    os.utime(data_dir() / "screenshot.jpg", (old, old))
    sync.poll_controller_command()
    assert len(uploads) == 2 and request_file.exists()

    monkeypatch.setattr(sync, "SCREENSHOT_HELPER", tmp_path / "fehlt")
    request_file.unlink()
    sync.poll_controller_command()
    assert not request_file.exists()


def test_display_reports_status_every_poll_while_overview_is_open(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("sync_device_token", "device-token")
    monkeypatch.setattr(sync, "SCREENSHOT_HELPER", tmp_path / "fehlt")
    wanted = {"value": False}
    requested = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"command": null, "screenshot": %s}' % (b"true" if wanted["value"] else b"false")

    def fake_urlopen(request, timeout):
        requested.append(request.full_url.rsplit("/api/", 1)[1])
        return Response()

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)
    sync.poll_controller_command()
    assert requested == ["sync/commands"]
    wanted["value"] = True
    sync.poll_controller_command()
    assert requested == ["sync/commands", "sync/commands", "sync/status"]
