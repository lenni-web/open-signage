from __future__ import annotations

import json
from pathlib import Path

from .database import data_dir

DEFAULT_CONFIG = {
    "cec_address": "0",
    "activate_source": True,
    "fallback_hdmi_signal": True,
    "schedule_enabled": False,
    "schedule_entries": [],
}


def _read_json(path: Path, fallback: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {**fallback, **value} if isinstance(value, dict) else fallback.copy()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback.copy()


def display_config() -> dict:
    config = _read_json(data_dir() / "display-control.json", DEFAULT_CONFIG)
    if not config.get("schedule_entries") and "schedule_on" in config:
        weekdays = config.get("schedule_weekdays") or list(range(7))
        config["schedule_entries"] = [
            {"weekday": day, "on": config.get("schedule_on", "08:00"),
             "off": config.get("schedule_off", "22:00")}
            for day in weekdays
        ]
    if not isinstance(config.get("schedule_entries"), list):
        config["schedule_entries"] = []
    for legacy in ("schedule_weekdays", "schedule_on", "schedule_off"):
        config.pop(legacy, None)
    return config


def save_display_config(config: dict) -> dict:
    path = data_dir() / "display-control.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return config


def display_status() -> dict:
    return _read_json(data_dir() / "display-control-status.json", {
        "cec_available": None,
        "hdmi_fallback_available": None,
        "power_status": "unknown",
        "method": None,
        "message": "Status wurde noch nicht abgefragt.",
        "updated_at": None,
    })


def request_display_action(action: str) -> None:
    (data_dir() / "display-control-request").write_text(action, encoding="utf-8")
