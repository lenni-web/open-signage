"""Live-Übertragung aus OBS über MediaMTX (WHIP zum Senden, WHEP zum Abspielen)."""

from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .auth import device_mode, get_setting, set_setting
from .database import data_dir

LIVE_PATH = "live"
MEDIAMTX_BINARY = Path("/usr/local/lib/open-signage/mediamtx")
SYSTEM_ACTION_UNIT = Path("/etc/systemd/system/open-signage-system-action.path")
API_URL = "http://127.0.0.1:9997"
WEBRTC_URL = "http://127.0.0.1:8889"
WEBRTC_PORT = 8889
RTSP_PORT = 8554
# Ohne Signal endet eine automatisch beendbare Übernahme erst nach dieser
# Schonfrist, damit kurze Aussetzer in OBS die Wiedergabe nicht abbrechen.
AUTO_END_GRACE = timedelta(seconds=20)
CONTROLLER_STATE_TTL = 2.0

_controller_cache: dict = {"at": 0.0, "state": None}
_controller_lock = threading.Lock()


def config_path() -> Path:
    return data_dir() / "mediamtx.yml"


def _secret(key: str) -> str:
    value = get_setting(key)
    if not value:
        value = secrets.token_urlsafe(18)
        set_setting(key, value)
    return value


def publish_password() -> str:
    return _secret("live_publish_password")


def regenerate_publish_password() -> str:
    set_setting("live_publish_password", secrets.token_urlsafe(18))
    write_config()
    return publish_password()


def read_password() -> str:
    """Gemeinsames Leserecht des Controllers für seine Displays."""
    if device_mode() == "display":
        return get_setting("live_read_password") or ""
    return _secret("live_read_password")


def _controller_host() -> str:
    controller = get_setting("controller_url") or get_setting("master_url") or ""
    host = urlparse(controller).hostname or ""
    return f"[{host}]" if ":" in host else host


def render_config() -> str:
    q = json.dumps
    display = device_mode() == "display"
    lines = [
        "# Wird von Open Signage erzeugt und bei Änderungen überschrieben.",
        "logLevel: warn",
        "logDestinations: [stdout]",
        "api: true",
        "apiAddress: 127.0.0.1:9997",
        "rtmp: false",
        "hls: false",
        "srt: false",
        f"rtsp: {'false' if display else 'true'}",
        f"rtspAddress: :{RTSP_PORT}",
        "webrtc: true",
        f"webrtcAddress: :{WEBRTC_PORT}",
        "webrtcLocalUDPAddress: :8189",
        "authMethod: internal",
        "authInternalUsers:",
    ]
    if not display:
        lines += [
            "  - user: obs",
            f"    pass: {q(publish_password())}",
            "    ips: []",
            "    permissions:",
            "      - action: publish",
            f"        path: {LIVE_PATH}",
            "  - user: display",
            f"    pass: {q(read_password())}",
            "    ips: []",
            "    permissions:",
            "      - action: read",
            f"        path: {LIVE_PATH}",
        ]
    lines += [
        "  - user: any",
        "    pass:",
        "    ips: ['127.0.0.1', '::1']",
        "    permissions:",
        "      - action: read",
        f"        path: {LIVE_PATH}",
        "      - action: api",
        "paths:",
        f"  {LIVE_PATH}:",
    ]
    host = _controller_host()
    password = read_password()
    if display and host and password:
        lines += [
            f"    source: {q(f'rtsp://display:{password}@{host}:{RTSP_PORT}/{LIVE_PATH}')}",
            "    sourceOnDemand: true",
        ]
    else:
        lines.append("    source: publisher")
    return "\n".join(lines) + "\n"


def write_config() -> bool:
    """Schreibt die MediaMTX-Konfiguration; MediaMTX lädt sie bei Änderung selbst neu."""
    path = config_path()
    content = render_config()
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except OSError:
        pass
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o640)
    temporary.replace(path)
    return True


def server_installed() -> bool:
    return MEDIAMTX_BINARY.is_file()


def request_server_setup(force: bool = False) -> bool:
    """Fordert die feste root-Aktion zur MediaMTX-Einrichtung an (höchstens einmal täglich)."""
    if not SYSTEM_ACTION_UNIT.is_file() or (server_installed() and not force):
        return False
    last = get_setting("live_setup_requested_at")
    if not force and last and datetime.now(UTC) - datetime.fromisoformat(last) < timedelta(days=1):
        return False
    request = data_dir() / "system-action-request"
    if request.exists():
        return False
    request.write_text("setup_live", encoding="utf-8")
    set_setting("live_setup_requested_at", datetime.now(UTC).isoformat())
    return True


def stream_status() -> dict:
    """Fragt die lokale MediaMTX-API, ob OBS gerade sendet."""
    try:
        with urllib.request.urlopen(f"{API_URL}/v3/paths/get/{LIVE_PATH}", timeout=1) as response:
            data = json.load(response)
        return {"server_running": True, "available": bool(data.get("available", data.get("ready")))}
    except urllib.error.HTTPError:
        # 404 bedeutet: Server läuft, aber OBS sendet nicht.
        return {"server_running": True, "available": False}
    except (OSError, ValueError):
        return {"server_running": False, "available": False}


def _flag(key: str, default: bool) -> bool:
    value = get_setting(key)
    return default if value is None else value == "1"


def _now() -> datetime:
    return datetime.now().astimezone()


def live_schedule() -> dict:
    try:
        value = json.loads(get_setting("live_schedule") or "{}")
    except ValueError:
        value = {}
    if not isinstance(value, dict):
        value = {}
    entries = [entry for entry in value.get("entries") or [] if isinstance(entry, dict)]
    return {"enabled": bool(value.get("enabled")), "sound": bool(value.get("sound", True)), "entries": entries}


def save_live_schedule(schedule: dict) -> dict:
    set_setting("live_schedule", json.dumps(schedule))
    return live_schedule()


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def schedule_window(entries: list[dict], now: datetime) -> tuple[datetime | None, datetime | None]:
    """Ende des aktuell laufenden und Beginn des nächsten Zeitfensters.

    Wochentage zählen ab Montag (0). Endet ein Fenster vor seinem Beginn, reicht
    es über Mitternacht in den Folgetag.
    """
    current_end = None
    next_start = None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(-1, 8):
        day = midnight + timedelta(days=offset)
        for entry in entries:
            try:
                if day.weekday() != int(entry["weekday"]):
                    continue
                start_minutes, end_minutes = _minutes(entry["start"]), _minutes(entry["end"])
            except (KeyError, TypeError, ValueError):
                continue
            start = day + timedelta(minutes=start_minutes)
            end = day + timedelta(days=0 if end_minutes > start_minutes else 1, minutes=end_minutes)
            if start <= now < end:
                current_end = max(current_end, end) if current_end else end
            elif start > now and (next_start is None or start < next_start):
                next_start = start
    return current_end, next_start


def set_takeover(active: bool, auto_end: bool = True, sound: bool = True) -> dict:
    set_setting("live_takeover", "1" if active else "0")
    set_setting("live_takeover_auto_end", "1" if auto_end else "0")
    set_setting("live_takeover_sound", "1" if sound else "0")
    set_setting("live_takeover_started_at", datetime.now(UTC).isoformat() if active else "")
    set_setting("live_last_available_at", "")
    if active:
        set_setting("live_schedule_suppressed_until", "")
    return local_state()


def stop_takeover(auto_end: bool = True, sound: bool = True) -> dict:
    """Beendet Live sofort – auch ein laufendes Zeitfenster bis zu dessen Ende."""
    schedule = live_schedule()
    window_end, _ = schedule_window(schedule["entries"], _now()) if schedule["enabled"] else (None, None)
    set_setting("live_schedule_suppressed_until", window_end.isoformat() if window_end else "")
    return set_takeover(False, auto_end, sound)


def local_state(now: datetime | None = None) -> dict:
    """Live-Zustand eines Controllers oder Einzelgeräts.

    ``takeover`` ist der wirksame Zustand für Player und Displays: manuell
    übernommen oder ein Zeitfenster läuft und OBS sendet.
    """
    now = now or _now()
    status = stream_status()
    manual = _flag("live_takeover", False)
    auto_end = _flag("live_takeover_auto_end", True)
    last = get_setting("live_last_available_at")
    last_at = datetime.fromisoformat(last) if last else None
    if status["available"]:
        if not last_at or now - last_at > timedelta(seconds=5):
            set_setting("live_last_available_at", now.astimezone(UTC).isoformat())
            last_at = now
    elif manual and auto_end and last_at and now - last_at > AUTO_END_GRACE:
        set_takeover(False, auto_end, _flag("live_takeover_sound", True))
        manual = False
    # Kurze Aussetzer überbrücken, damit ein Zeitfenster nicht flackert.
    recently_available = status["available"] or bool(last_at and now - last_at <= AUTO_END_GRACE)

    schedule = live_schedule()
    window_end, next_start = (schedule_window(schedule["entries"], now)
                              if schedule["enabled"] else (None, None))
    suppressed_until = get_setting("live_schedule_suppressed_until")
    if window_end and suppressed_until and now < datetime.fromisoformat(suppressed_until):
        window_end = None
    schedule_takeover = bool(window_end) and recently_available
    return {
        **status,
        "takeover": manual or schedule_takeover,
        "manual_takeover": manual,
        "schedule_takeover": schedule_takeover,
        "takeover_started_at": get_setting("live_takeover_started_at") or None,
        "auto_end": auto_end,
        "sound": _flag("live_takeover_sound", True) if manual else schedule["sound"],
        "schedule": schedule,
        "schedule_active_until": window_end.isoformat() if window_end else None,
        "schedule_next": next_start.isoformat() if next_start else None,
    }


def _controller_state() -> dict:
    with _controller_lock:
        if _controller_cache["state"] is not None and time.monotonic() - _controller_cache["at"] < CONTROLLER_STATE_TTL:
            return _controller_cache["state"]
    controller = (get_setting("controller_url") or get_setting("master_url") or "").rstrip("/") + "/"
    token = get_setting("sync_device_token") or ""
    state = {"server_running": False, "available": False, "takeover": False, "sound": True}
    if controller.startswith(("http://", "https://")) and token:
        request = urllib.request.Request(urljoin(controller, "api/sync/live"),
                                         headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                remote = json.load(response)
            state = {"server_running": bool(remote.get("server_running")),
                     "available": bool(remote.get("available")),
                     "takeover": bool(remote.get("takeover")),
                     "sound": bool(remote.get("sound", True))}
        except (OSError, ValueError):
            pass
    with _controller_lock:
        _controller_cache.update(at=time.monotonic(), state=state)
    return state


def player_state() -> dict:
    """Zustand für Player: Displays übernehmen Signal und Übernahme vom Controller."""
    if device_mode() == "display":
        state = _controller_state()
    else:
        state = local_state()
    return {key: state[key] for key in ("available", "takeover", "sound")}


def whep_request(method: str, path: str, body: bytes | None = None) -> tuple[int, dict, bytes]:
    headers = {"Content-Type": "application/sdp"} if body is not None else {}
    request = urllib.request.Request(f"{WEBRTC_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()
    except OSError:
        # MediaMTX läuft nicht oder ist nicht erreichbar.
        return 502, {}, b""
