"""Anmeldung, Sitzungen, Player-Freischaltung und Zugriff auf Medien."""

import pytest
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

from open_signage.auth import local_player_client
from open_signage.main import app

from helpers import VALID_PNG


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
        assert client.get("/api/player/config", headers=headers).json() == {
            "transition_ms": 4000, "live": {"available": False, "takeover": False, "sound": True}}
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


def upload_test_image(client) -> str:
    client.post("/api/system/login", json={"password": "open-signage"})
    item = client.post(
        "/api/content/upload", files={"file": ("bild.png", VALID_PNG, "image/png")}
    ).json()
    client.post("/api/system/logout")
    return item["source"]


def test_media_is_served_to_lan_players_but_not_to_external_clients(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as local:
        source = upload_test_image(local)
    with TestClient(app, client=("192.168.1.50", 50000)) as lan:
        assert lan.get(source).status_code == 200
        assert "open_signage_player" in lan.get("/api/player/bootstrap").cookies
    with TestClient(app, client=("203.0.113.10", 50000)) as external:
        assert external.get(source).status_code == 401
        assert external.get("/media/nicht-vorhanden.png").status_code == 401
        assert external.get("/api/player/bootstrap").status_code == 401
        paired = external.post("/api/player/pair", json={"password": "open-signage"})
        assert paired.status_code == 200
        assert "open_signage_player" in paired.cookies
        assert external.get(source).status_code == 200
        external.cookies.clear()
        token = paired.json()["token"]
        assert external.get(source, headers={"Authorization": f"Bearer {token}"}).status_code == 200
        external.post("/api/system/login", json={"password": "open-signage"})
        assert external.get(source).status_code == 200


def test_disabled_lan_access_requires_player_pairing_except_for_local_kiosk(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as local:
        source = upload_test_image(local)
        local.post("/api/system/login", json={"password": "open-signage"})
        assert local.get("/api/system/player-access").json() == {"lan_access": True}
        assert local.patch("/api/system/player-access", json={"lan_access": False}).json() == {"lan_access": False}
        local.post("/api/system/logout")
    with TestClient(app, client=("127.0.0.1", 50000)) as kiosk:
        assert kiosk.get("/api/player/bootstrap").status_code == 200
        kiosk.cookies.clear()
        assert kiosk.get(source).status_code == 200
    with TestClient(app, client=("192.168.1.50", 50000)) as lan:
        assert lan.get("/api/player/bootstrap").status_code == 401
        assert lan.get(source).status_code == 401
        assert lan.post("/api/player/pair", json={"password": "open-signage"}).status_code == 200
        assert lan.get(source).status_code == 200


def test_player_access_setting_requires_login(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/system/player-access").status_code == 401
        assert client.patch("/api/system/player-access", json={"lan_access": False}).status_code == 401
