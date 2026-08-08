from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .database import data_dir

UPDATE_HELPER = Path("/usr/local/sbin/open-signage-system-update")
UPDATE_PATH_UNIT = Path("/etc/systemd/system/open-signage-update.path")


def update_available() -> bool:
    if os.environ.get("OPEN_SIGNAGE_ENABLE_SYSTEM_UPDATE") == "1":
        return True
    return UPDATE_HELPER.is_file() and UPDATE_PATH_UNIT.is_file()


def trigger_path() -> Path:
    override = os.environ.get("OPEN_SIGNAGE_UPDATE_TRIGGER")
    return Path(override) if override else data_dir() / "update.request"


def status_path() -> Path:
    override = os.environ.get("OPEN_SIGNAGE_UPDATE_STATUS")
    return Path(override) if override else data_dir() / "system-update.json"


def log_path() -> Path:
    override = os.environ.get("OPEN_SIGNAGE_UPDATE_LOG")
    return Path(override) if override else data_dir() / "system-update.log"


def update_status() -> dict:
    status = {
        "available": update_available(),
        "status": "idle",
        "message": "Noch kein Systemupdate ausgeführt.",
        "started_at": None,
        "finished_at": None,
        "log": [],
    }
    try:
        loaded = json.loads(status_path().read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            status.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass

    try:
        lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
        status["log"] = lines[-40:]
    except OSError:
        pass
    status["available"] = update_available()
    if trigger_path().exists() and status["status"] != "running":
        status.update(status="queued", message="Systemupdate wurde angefordert.")
    return status


def request_update() -> dict:
    if not update_available():
        raise FileNotFoundError(
            "Systemupdates sind nur nach der Raspberry-Pi-Installation verfügbar."
        )
    current = update_status()
    if current["status"] in {"queued", "running"}:
        raise RuntimeError("Ein Systemupdate läuft bereits.")

    trigger = trigger_path()
    trigger.parent.mkdir(parents=True, exist_ok=True)
    trigger.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return {
        "available": True,
        "status": "queued",
        "message": "Systemupdate wurde angefordert.",
        "started_at": None,
        "finished_at": None,
        "log": [],
    }
