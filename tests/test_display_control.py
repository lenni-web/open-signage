"""Bildschirmsteuerung per HDMI-CEC/DPMS und Zeitpläne."""

import json
import runpy
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage.display_control import schedule_analysis
from open_signage.main import app

from helpers import PROJECT_ROOT


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


def test_schedule_analysis_detects_overlap_and_next_action():
    now = datetime(2026, 8, 11, 7, 0).astimezone()
    result = schedule_analysis({"schedule_entries": [
        {"weekday": 1, "on": "08:00", "off": "10:00"},
        {"weekday": 1, "on": "09:00", "off": "11:00"},
    ]}, now)
    assert result["conflicts"] == [{"first": 0, "second": 1}]
    assert result["next_action"]["action"] == "on"
