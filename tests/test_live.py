"""Live-Übertragung aus OBS über MediaMTX."""

import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage import live
from open_signage.auth import get_setting, set_setting
from open_signage.database import connect, initialize
from open_signage.main import app
from open_signage.sync import safe_sync_from_controller, snapshot as sync_snapshot


def offline_live(monkeypatch, available=False):
    monkeypatch.setattr("open_signage.live.stream_status",
                        lambda: {"server_running": True, "available": available})


def test_mediamtx_config_matches_device_role(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    set_setting("device_role", "controller")
    config = live.render_config()
    assert f'pass: "{get_setting("live_publish_password")}"' in config
    assert "action: publish" in config and "source: publisher" in config
    assert "ips: ['127.0.0.1', '::1']" in config
    assert live.write_config() is True
    assert live.write_config() is False
    assert (tmp_path / "mediamtx.yml").read_text() == config

    set_setting("device_role", "display")
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("live_read_password", "geheim")
    display_config = live.render_config()
    assert "user: obs" not in display_config and "action: publish" not in display_config
    assert 'source: "rtsp://display:geheim@controller.local:8554/live"' in display_config
    assert "sourceOnDemand: true" in display_config
    assert "rtsp: false" in display_config


def test_live_takeover_reaches_player_and_ends_automatically(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    offline_live(monkeypatch, available=True)
    with TestClient(app) as client:
        assert client.post("/api/live/takeover", json={"active": True}).status_code == 401
        client.post("/api/system/login", json={"password": "open-signage"})
        status = client.get("/api/live").json()
        assert status["takeover"] is False
        assert status["publish_path"] == "/live/whip"
        assert status["publish_token"].startswith("obs:")
        started = client.post("/api/live/takeover", json={"active": True, "auto_end": True, "sound": False}).json()
        assert started["takeover"] is True
        token = client.get("/api/player/bootstrap").json()["token"]
        config = client.get("/api/player/config", headers={"Authorization": f"Bearer {token}"}).json()
        assert config["live"] == {"available": True, "takeover": True, "sound": False}
        assert get_setting("live_last_available_at")

        offline_live(monkeypatch, available=False)
        assert client.get("/api/live").json()["takeover"] is True
        set_setting("live_last_available_at", (datetime.now(UTC) - timedelta(seconds=30)).isoformat())
        assert client.get("/api/live").json()["takeover"] is False

        client.post("/api/live/takeover", json={"active": True, "auto_end": False})
        set_setting("live_last_available_at", (datetime.now(UTC) - timedelta(seconds=30)).isoformat())
        assert client.get("/api/live").json()["takeover"] is True
        assert client.post("/api/live/takeover", json={"active": False}).json()["takeover"] is False


def test_whep_proxy_forwards_offer_for_authorized_players(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    calls = []

    def fake_whep(method, path, body=None):
        calls.append((method, path, body))
        if method == "POST":
            return 201, {"Location": "/live/whep/0a1b-2c3d"}, b"v=0 answer"
        return 200, {}, b""

    monkeypatch.setattr("open_signage.live.whep_request", fake_whep)
    with TestClient(app, client=("192.168.1.50", 50000)) as lan:
        answer = lan.post("/api/player/live/whep", content=b"v=0 offer",
                          headers={"Content-Type": "application/sdp"})
        assert answer.status_code == 201
        assert answer.text == "v=0 answer"
        assert answer.headers["content-type"].startswith("application/sdp")
        assert answer.headers["location"] == "/api/player/live/session/0a1b-2c3d"
        assert lan.delete("/api/player/live/session/0a1b-2c3d").status_code == 204
        assert lan.delete("/api/player/live/session/..%2Fetc").status_code == 404
    assert calls == [("POST", "/live/whep", b"v=0 offer"), ("DELETE", "/live/whep/0a1b-2c3d", None)]
    with TestClient(app, client=("203.0.113.10", 50000)) as external:
        assert external.post("/api/player/live/whep", content=b"v=0 offer").status_code == 401
    monkeypatch.setattr("open_signage.live.whep_request", lambda *args, **kwargs: (404, {}, b"not found"))
    with TestClient(app) as local:
        assert local.post("/api/player/live/whep", content=b"v=0 offer").status_code == 503


def test_controller_shares_live_state_and_read_access_with_displays(tmp_path: Path, monkeypatch):
    controller_dir = tmp_path / "controller"
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(controller_dir))
    offline_live(monkeypatch, available=True)
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        client.patch("/api/system/device", json={"role": "controller", "controller_url": "", "current_password": "open-signage"})
        pairing = client.get("/api/system/device").json()["pairing_code"]
        token = client.post("/api/sync/register", json={
            "device_id": "display-1", "name": "Foyer", "pairing_token": pairing}).json()["device_token"]
        assert client.get("/api/sync/live").status_code == 401
        client.post("/api/live/takeover", json={"active": True})
        shared = client.get("/api/sync/live", headers={"Authorization": f"Bearer {token}"}).json()
        assert shared == {"server_running": True, "available": True, "takeover": True, "sound": True}
        controller_data = sync_snapshot()
    assert controller_data["live"]["read_password"] == get_setting("live_read_password")

    display_dir = tmp_path / "display"
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(display_dir))
    initialize()
    set_setting("device_role", "display")
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("sync_device_token", "device-token")
    monkeypatch.setattr("open_signage.sync._request_json", lambda *args, **kwargs: controller_data)
    assert safe_sync_from_controller()["status"] == "synchronized"
    read_password = controller_data["live"]["read_password"]
    assert f"rtsp://display:{read_password}@controller.local:8554/live" in (display_dir / "mediamtx.yml").read_text()

    class FakeResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    requested = []

    def fake_urlopen(request, timeout=0):
        requested.append((request.full_url, request.get_header("Authorization")))
        return FakeResponse(json.dumps(shared).encode())

    monkeypatch.setattr("open_signage.live.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("open_signage.live._controller_cache", {"at": 0.0, "state": None})
    assert live.player_state() == {"available": True, "takeover": True, "sound": True}
    assert requested == [("http://controller.local:8080/api/sync/live", "Bearer device-token")]


def test_live_content_survives_lossless_table_upgrade(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    with connect() as connection:
        sql = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'content'").fetchone()[0]
        connection.execute("INSERT INTO playlists(id, name) VALUES (2, 'Abend')")
        connection.execute("ALTER TABLE content RENAME TO content_new")
        connection.execute(sql.replace(", 'live'", ""))
        connection.execute(
            "INSERT INTO content(name, kind, source, playlist_id, schedule_daily_start, play_to_end) "
            "VALUES ('Bestand', 'website', 'https://example.org', 2, '18:00', 1)")
        connection.execute("DROP TABLE content_new")
    initialize()
    with connect() as connection:
        row = connection.execute("SELECT * FROM content WHERE name = 'Bestand'").fetchone()
        assert (row["playlist_id"], row["schedule_daily_start"], row["play_to_end"]) == (2, "18:00", 1)
        assert "'live'" in connection.execute("SELECT sql FROM sqlite_master WHERE name = 'content'").fetchone()[0]
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'idx_content_playlist'").fetchone()
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post("/api/content/live", json={"name": "Gottesdienst live", "duration_seconds": 600})
        assert created.status_code == 201
        assert created.json()["kind"] == "live"
        assert created.json()["muted"] is False
        token = client.get("/api/player/bootstrap").json()["token"]
        player_items = client.get("/api/player/content", headers={"Authorization": f"Bearer {token}"}).json()
        assert any(item["kind"] == "live" for item in player_items)


def test_missing_live_server_is_requested_once(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    unit = tmp_path / "open-signage-system-action.path"
    monkeypatch.setattr("open_signage.live.SYSTEM_ACTION_UNIT", unit)
    monkeypatch.setattr("open_signage.live.MEDIAMTX_BINARY", tmp_path / "mediamtx")
    assert live.request_server_setup() is False
    unit.write_text("[Path]")
    assert live.request_server_setup() is True
    assert (tmp_path / "system-action-request").read_text() == "setup_live"
    (tmp_path / "system-action-request").unlink()
    assert live.request_server_setup() is False
    assert live.request_server_setup(force=True) is True


def test_whep_proxy_reports_unavailable_live_server(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))

    def refused(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr("open_signage.live.urllib.request.urlopen", refused)
    with TestClient(app) as client:
        assert client.post("/api/player/live/whep", content=b"v=0 offer").status_code == 503


SUNDAY_SERVICE = {"enabled": True, "sound": False,
                  "entries": [{"weekday": 6, "start": "11:00", "end": "12:30"}]}


def local_time(day: int, hour: int, minute: int = 0) -> datetime:
    # 2026-10-11 ist ein Sonntag.
    return datetime(2026, 10, day, hour, minute).astimezone()


def test_live_schedule_windows_cover_weekdays_and_overnight():
    entries = SUNDAY_SERVICE["entries"] + [{"weekday": 5, "start": "23:00", "end": "01:00"}]
    assert live.schedule_window(entries, local_time(11, 11, 30))[0] == local_time(11, 12, 30)
    current, upcoming = live.schedule_window(entries, local_time(11, 10, 0))
    assert current is None and upcoming == local_time(11, 11, 0)
    assert live.schedule_window(entries, local_time(11, 0, 30))[0] == local_time(11, 1, 0)
    assert live.schedule_window(entries, local_time(11, 12, 30))[0] is None
    assert live.schedule_window(entries, local_time(12, 11, 30))[0] is None


def test_live_schedule_takes_over_only_with_signal_inside_window(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    live.save_live_schedule(SUNDAY_SERVICE)
    offline_live(monkeypatch, available=False)
    waiting = live.local_state(local_time(11, 11, 5))
    assert waiting["takeover"] is False
    assert waiting["schedule_active_until"] is not None

    offline_live(monkeypatch, available=True)
    running = live.local_state(local_time(11, 11, 10))
    assert running["takeover"] is True and running["schedule_takeover"] is True
    assert running["manual_takeover"] is False and running["sound"] is False

    offline_live(monkeypatch, available=False)
    assert live.local_state(local_time(11, 11, 10) + timedelta(seconds=10))["takeover"] is True
    assert live.local_state(local_time(11, 11, 11))["takeover"] is False

    offline_live(monkeypatch, available=True)
    assert live.local_state(local_time(11, 12, 29))["takeover"] is True
    after = live.local_state(local_time(11, 12, 31))
    assert after["takeover"] is False
    assert after["schedule_next"] == local_time(18, 11, 0).isoformat()


def test_ending_live_early_suspends_current_window_only(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    live.save_live_schedule(SUNDAY_SERVICE)
    offline_live(monkeypatch, available=True)
    monkeypatch.setattr("open_signage.live._now", lambda: local_time(11, 11, 30))
    assert live.local_state()["takeover"] is True
    assert live.stop_takeover()["takeover"] is False
    assert live.local_state(local_time(11, 12, 0))["takeover"] is False
    assert live.local_state(local_time(18, 11, 30))["takeover"] is True
    assert live.set_takeover(True)["takeover"] is True
    assert live.local_state(local_time(11, 12, 0))["schedule_takeover"] is True


def test_live_schedule_api_validates_and_reaches_players_and_displays(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    offline_live(monkeypatch, available=True)
    monkeypatch.setattr("open_signage.live._now", lambda: local_time(11, 11, 30))
    with TestClient(app) as client:
        assert client.put("/api/live/schedule", json=SUNDAY_SERVICE).status_code == 401
        client.post("/api/system/login", json={"password": "open-signage"})
        invalid = {"enabled": True, "entries": [{"weekday": 6, "start": "11:00", "end": "11:00"}]}
        assert client.put("/api/live/schedule", json=invalid).status_code == 422
        invalid["entries"][0]["end"] = "25:00"
        assert client.put("/api/live/schedule", json=invalid).status_code == 422
        saved = client.put("/api/live/schedule", json=SUNDAY_SERVICE).json()
        assert saved["schedule"] == SUNDAY_SERVICE
        assert saved["schedule_takeover"] is True
        assert client.get("/api/live").json()["schedule"]["entries"][0]["start"] == "11:00"
        token = client.get("/api/player/bootstrap").json()["token"]
        config = client.get("/api/player/config", headers={"Authorization": f"Bearer {token}"}).json()
        assert config["live"] == {"available": True, "takeover": True, "sound": False}

        client.patch("/api/system/device", json={"role": "controller", "controller_url": "", "current_password": "open-signage"})
        pairing = client.get("/api/system/device").json()["pairing_code"]
        device_token = client.post("/api/sync/register", json={
            "device_id": "display-1", "name": "Foyer", "pairing_token": pairing}).json()["device_token"]
        shared = client.get("/api/sync/live", headers={"Authorization": f"Bearer {device_token}"}).json()
        assert shared["takeover"] is True and shared["sound"] is False

        stopped = client.post("/api/live/takeover", json={"active": False}).json()
        assert stopped["takeover"] is False


def test_admin_session_can_open_live_preview_from_outside_the_lan(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("open_signage.live.whep_request",
                        lambda method, path, body=None: (201, {"Location": "/live/whep/abc"}, b"v=0 answer"))
    with TestClient(app, client=("203.0.113.10", 50000)) as external:
        assert external.post("/api/player/live/whep", content=b"v=0 offer").status_code == 401
        external.post("/api/system/login", json={"password": "open-signage"})
        preview = external.post("/api/player/live/whep", content=b"v=0 offer",
                                headers={"Content-Type": "application/sdp"})
        assert preview.status_code == 201
        assert external.delete(preview.headers["location"]).status_code == 204
