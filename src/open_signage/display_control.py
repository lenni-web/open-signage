from __future__ import annotations

import json
from datetime import datetime, timedelta
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


def schedule_analysis(config: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    entries = config.get("schedule_entries") or []
    conflicts = []
    intervals = []
    for index, entry in enumerate(entries):
        start = entry["weekday"] * 1440 + int(entry["on"][:2]) * 60 + int(entry["on"][3:])
        end = entry["weekday"] * 1440 + int(entry["off"][:2]) * 60 + int(entry["off"][3:])
        if end <= start: end += 7 * 1440 if entry["on"] == entry["off"] else 1440
        intervals.append((start, end, index))
        intervals.append((start + 7 * 1440, end + 7 * 1440, index))
    for left in range(len(entries)):
        for right in range(left + 1, len(entries)):
            overlap = any(a < d and c < b for a, b, i in intervals for c, d, j in intervals
                          if i == left and j == right)
            if overlap: conflicts.append({"first": left, "second": right})
    events = []
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    for week in range(2):
        for entry in entries:
            start = monday + timedelta(days=entry["weekday"] + week * 7,
                                       hours=int(entry["on"][:2]), minutes=int(entry["on"][3:]))
            end_day = entry["weekday"] + week * 7 + (1 if entry["off"] <= entry["on"] else 0)
            end = monday + timedelta(days=end_day, hours=int(entry["off"][:2]), minutes=int(entry["off"][3:]))
            events.extend([("on", start), ("off", end)])
    future = sorted(
        ((action, moment) for action, moment in events if moment > now), key=lambda item: item[1]
    )
    next_event = future[0] if future else None
    return {"conflicts": conflicts, "next_action": (
        {"action": next_event[0], "at": next_event[1].isoformat()} if next_event else None
    )}


def display_status() -> dict:
    return _read_json(data_dir() / "display-control-status.json", {
        "cec_available": None,
        "hdmi_fallback_available": None,
        "power_status": "unknown",
        "method": None,
        "cec_adapter": None,
        "output_name": None,
        "message": "Status wurde noch nicht abgefragt.",
        "updated_at": None,
    })


def request_display_action(action: str) -> None:
    (data_dir() / "display-control-request").write_text(action, encoding="utf-8")
