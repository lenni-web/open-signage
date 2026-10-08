"""Playlists und Zeitpläne für Inhalte und Playlists."""

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage.main import app
from open_signage.routes.common import scheduled_now


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
