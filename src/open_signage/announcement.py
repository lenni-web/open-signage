"""Sofortmeldung: ein Hinweistext, der auf allen Playern über dem laufenden Inhalt erscheint."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from .auth import device_mode, get_setting, set_setting

# top/bottom: Laufband oben (Standard) bzw. unten; fullscreen: Vollbild.
STYLES = {"top", "bottom", "fullscreen"}
MAX_TEXT = 500


def _stored() -> dict | None:
    try:
        value = json.loads(get_setting("announcement") or "null")
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("text") else None


def local_announcement(now: datetime | None = None) -> dict | None:
    """Die auf diesem Gerät gesetzte Meldung, solange sie nicht abgelaufen ist."""
    item = _stored()
    if not item:
        return None
    until = item.get("until")
    if until and datetime.fromisoformat(until) <= (now or datetime.now(UTC)):
        return None
    return {key: item.get(key) for key in ("text", "style", "until", "created_at")}


def set_announcement(text: str, style: str, minutes: int | None) -> dict:
    now = datetime.now(UTC)
    item = {"text": text.strip()[:MAX_TEXT], "style": style if style in STYLES else "top",
            "until": (now + timedelta(minutes=minutes)).isoformat() if minutes else None,
            "created_at": now.isoformat()}
    set_setting("announcement", json.dumps(item, ensure_ascii=False))
    return item


def clear_announcement() -> None:
    set_setting("announcement", "null")


def player_announcement() -> dict | None:
    """Meldung für den Player: Displays übernehmen die Meldung des Controllers."""
    if device_mode() == "display":
        from .live import controller_state
        return controller_state().get("announcement")
    return local_announcement()
