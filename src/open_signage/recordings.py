"""Aufnahmen der Live-Übertragungen: auflisten, die letzten behalten, Ton für den Download umwandeln.

MediaMTX schreibt jede Übertragung unverändert als fragmentiertes MP4 (Bild H.264, Ton Opus).
Weil nicht jedes Programm Opus in MP4 abspielt, lässt sich eine Kopie mit AAC-Ton erzeugen;
das Bild wird dabei nur kopiert.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .database import data_dir
from .live import LIVE_PATH, stream_status
from .upload_security import MIN_FREE_BYTES

KEEP = 10
NAME_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})-\d+\.mp4$")
# Eine Datei, in die MediaMTX gerade noch schreibt, gilt als laufende Aufnahme.
ACTIVE_SECONDS = 15
FFMPEG = "ffmpeg"

_conversions: dict[str, dict] = {}
_lock = threading.Lock()


def recordings_dir() -> Path:
    return data_dir() / "recordings" / LIVE_PATH


def converted_path(name: str) -> Path:
    return recordings_dir() / "aac" / name


def recording_path(name: str) -> Path:
    if not NAME_PATTERN.match(name):
        raise LookupError(name)
    path = recordings_dir() / name
    if not path.is_file():
        raise LookupError(name)
    return path


def _started_at(name: str) -> datetime:
    year, month, day, hour, minute, second = (int(part) for part in NAME_PATTERN.match(name).groups())
    return datetime(year, month, day, hour, minute, second).astimezone()


def _files() -> list[Path]:
    folder = recordings_dir()
    if not folder.is_dir():
        return []
    return sorted((path for path in folder.iterdir() if path.is_file() and NAME_PATTERN.match(path.name)),
                  key=lambda path: path.name, reverse=True)


def _is_active(path: Path, now: float, live: bool | None = None) -> bool:
    if now - path.stat().st_mtime > ACTIVE_SECONDS:
        return False
    return stream_status()["available"] if live is None else live


def list_recordings() -> list[dict]:
    now = time.time()
    live = None
    result = []
    for path in _files():
        stat = path.stat()
        started = _started_at(path.name)
        active = False
        if now - stat.st_mtime <= ACTIVE_SECONDS:
            live = stream_status()["available"] if live is None else live
            active = live
        converted = converted_path(path.name)
        with _lock:
            conversion = dict(_conversions.get(path.name) or {})
        if converted.is_file() and conversion.get("status") != "running":
            conversion = {"status": "done", "size_bytes": converted.stat().st_size}
        result.append({
            "name": path.name, "started_at": started.isoformat(),
            "duration_seconds": max(0, round(stat.st_mtime - started.timestamp())),
            "size_bytes": stat.st_size, "active": active, "conversion": conversion or None,
        })
    return result


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)
    converted_path(path.name).unlink(missing_ok=True)
    with _lock:
        _conversions.pop(path.name, None)


def cleanup(keep: int = KEEP) -> int:
    """Behält die neuesten Aufnahmen und gibt bei knappem Speicher ältere frei."""
    files = _files()
    if not files:
        return 0
    now = time.time()
    recent = any(now - path.stat().st_mtime <= ACTIVE_SECONDS for path in files)
    live = stream_status()["available"] if recent else False
    removed = 0
    for path in files[keep:]:
        if not _is_active(path, now, live):
            _remove(path); removed += 1
    # Wird der Speicher knapp, weichen die ältesten Aufnahmen – nie die laufende.
    reserve = 2 * max(MIN_FREE_BYTES, int(shutil.disk_usage(recordings_dir()).total * 0.05))
    for path in reversed(_files()):
        if shutil.disk_usage(recordings_dir()).free >= reserve:
            break
        if not _is_active(path, now, live):
            _remove(path); removed += 1
    return removed


def delete_recording(name: str) -> None:
    path = recording_path(name)
    if _is_active(path, time.time()):
        raise RuntimeError("Die Aufnahme läuft noch.")
    _remove(path)


def _convert(name: str, source: Path) -> None:
    target = converted_path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.mp4")
    try:
        result = subprocess.run(
            [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-map", "0:v", "-map", "0:a?", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(temporary)],
            capture_output=True, text=True, timeout=4 * 3600, check=False,
        )
        if result.returncode != 0 or not temporary.is_file():
            raise RuntimeError(result.stderr.strip()[-300:] or "ffmpeg ist fehlgeschlagen")
        temporary.replace(target)
        state = {"status": "done", "size_bytes": target.stat().st_size}
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        temporary.unlink(missing_ok=True)
        state = {"status": "failed", "message": str(error) or "Umwandlung fehlgeschlagen"}
    with _lock:
        if name in _conversions:
            _conversions[name] = state


def start_conversion(name: str, background: bool = True) -> dict:
    """Erzeugt eine Kopie mit AAC-Ton für Programme, die Opus nicht abspielen."""
    source = recording_path(name)
    if _is_active(source, time.time()):
        raise RuntimeError("Die Aufnahme läuft noch; umwandeln lässt sie sich nach dem Ende der Übertragung.")
    if converted_path(name).is_file():
        return {"status": "done"}
    with _lock:
        if (_conversions.get(name) or {}).get("status") == "running":
            return _conversions[name]
        _conversions[name] = {"status": "running"}
    if background:
        threading.Thread(target=_convert, args=(name, source), daemon=True).start()
    else:
        _convert(name, source)
    with _lock:
        return dict(_conversions.get(name) or {})


def download_name(name: str, converted: bool) -> str:
    started = _started_at(name)
    return f"Livestream {started:%Y-%m-%d %H-%M}{' (AAC-Ton)' if converted else ''}.mp4"
