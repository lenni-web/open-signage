"""Player-Schnittstellen, Heartbeat und Monitoring."""

from pathlib import Path

from fastapi.testclient import TestClient

from open_signage.database import connect
from open_signage.main import app
from open_signage.version import __version__


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
