"""Systeminformationen, Updates, Gerätemodus und Systemaktionen."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_signage.application_update import request_update as request_application_update, update_status as application_update_status
from open_signage.auth import get_setting, set_setting
from open_signage.database import initialize
from open_signage import system_info
from open_signage.main import app
from open_signage.system_update import request_update, update_status


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


def test_temperature_is_read_from_thermal_zone(monkeypatch):
    monkeypatch.setattr("open_signage.system_info._read_text",
                        lambda path: "48123" if path.endswith("thermal_zone0/temp") else None)
    assert system_info.temperature_celsius() == 48.1


def test_clock_status_warns_about_missing_sync_and_utc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("open_signage.system_info.TIMESYNC_FLAG", tmp_path / "synchronized")
    answers = {"--property=NTPSynchronized": "no", "--property=Timezone": "Etc/UTC"}
    monkeypatch.setattr("open_signage.system_info._run_text", lambda command: answers.get(command[2]))
    clock = system_info.clock_status()
    assert clock["synchronized"] is False and clock["timezone"] == "Etc/UTC"
    assert len(clock["warnings"]) == 2

    (tmp_path / "synchronized").write_text("")
    answers["--property=Timezone"] = "Europe/Berlin"
    clock = system_info.clock_status()
    assert clock["synchronized"] is True and clock["warnings"] == []


def test_monitoring_and_security_status_report_unsynchronized_clock(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("open_signage.system_info.TIMESYNC_FLAG", tmp_path / "synchronized")
    monkeypatch.setattr("open_signage.system_info._run_text",
                        lambda command: "no" if command[:2] == ["timedatectl", "show"] and "NTP" in command[2] else None)
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        monitoring = client.get("/api/system/monitoring").json()
        assert monitoring["clock"]["synchronized"] is False
        assert any("Zeitserver" in warning for warning in monitoring["warnings"])
        security = client.get("/api/system/security-status").json()
        assert security["checks"]["clock_synchronized"] is False
        assert "clock_synchronized" in security["warnings"]
