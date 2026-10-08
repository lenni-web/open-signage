"""Zustand dieses Geräts für Monitoring und für die Display-Übersicht des Controllers."""

from __future__ import annotations

import shutil
import socket
from datetime import UTC, datetime

from .auth import get_setting, screen_name
from .database import connect, data_dir
from .system_info import clock_status, temperature_celsius
from .version import __version__

PLAYER_ONLINE_SECONDS = 25


def player_status() -> dict:
    with connect() as connection:
        row = connection.execute("SELECT * FROM player_status WHERE id = 1").fetchone()
    if not row:
        return {"online": False, "state": "unknown", "last_seen": None}
    player = dict(row)
    age = (datetime.now(UTC) - datetime.fromisoformat(player["last_seen"])).total_seconds()
    player["online"] = age < PLAYER_ONLINE_SECONDS
    player["age_seconds"] = round(age)
    return player


def local_device_status() -> dict:
    disk = shutil.disk_usage(data_dir())
    player = player_status()
    return {
        "version": __version__,
        "screen_name": screen_name(),
        "hostname": socket.gethostname(),
        "player": {key: player.get(key) for key in ("online", "state", "content_name", "last_seen", "error")},
        "temperature_celsius": temperature_celsius(),
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
        "clock": clock_status(),
        "sync": {"last_success": get_setting("sync_last_success") or None,
                 "last_warning": get_setting("sync_last_warning") or None,
                 "last_error": get_setting("sync_last_error") or None},
        "reported_at": datetime.now(UTC).isoformat(),
    }
