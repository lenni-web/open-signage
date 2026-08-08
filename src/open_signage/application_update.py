from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .database import data_dir

UPDATE_HELPER = Path("/usr/local/sbin/open-signage-application-update")
UPDATE_PATH_UNIT = Path("/etc/systemd/system/open-signage-application-update.path")


def update_available() -> bool:
    if os.environ.get("OPEN_SIGNAGE_ENABLE_APPLICATION_UPDATE") == "1":
        return True
    return UPDATE_HELPER.is_file() and UPDATE_PATH_UNIT.is_file()


def trigger_path() -> Path:
    override = os.environ.get("OPEN_SIGNAGE_APPLICATION_UPDATE_TRIGGER")
    return Path(override) if override else data_dir() / "application-update.request"


def status_path() -> Path:
    override = os.environ.get("OPEN_SIGNAGE_APPLICATION_UPDATE_STATUS")
    return Path(override) if override else data_dir() / "application-update.json"


def log_path() -> Path:
    override = os.environ.get("OPEN_SIGNAGE_APPLICATION_UPDATE_LOG")
    return Path(override) if override else data_dir() / "application-update.log"


def update_status() -> dict:
    status = {
        "available": update_available(),
        "status": "idle",
        "message": "Noch kein Anwendungsupdate ausgeführt.",
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
        status["log"] = log_path().read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()[-40:]
    except OSError:
        pass
    status["available"] = update_available()
    if trigger_path().exists() and status["status"] != "running":
        status.update(status="queued", message="Anwendungsupdate wurde angefordert.")
    return status


def request_update() -> dict:
    if not update_available():
        raise FileNotFoundError(
            "Anwendungsupdates sind nur nach der Raspberry-Pi-Installation verfügbar."
        )
    if update_status()["status"] in {"queued", "running"}:
        raise RuntimeError("Ein Anwendungsupdate läuft bereits.")
    trigger = trigger_path()
    trigger.parent.mkdir(parents=True, exist_ok=True)
    trigger.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return {
        "available": True,
        "status": "queued",
        "message": "Anwendungsupdate wurde angefordert.",
        "started_at": None,
        "finished_at": None,
        "log": [],
    }
