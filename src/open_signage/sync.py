from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from . import live
from .auth import get_setting, screen_name, set_setting
from .database import connect, media_dir
from .display_control import display_config, save_display_config
from .media_files import file_sha256, referenced_media_files, remember_sha256

SYNCED_TABLES = ("playlists", "media_library", "content")


def pairing_token() -> str:
    token = get_setting("sync_pairing_token")
    if not token:
        token = secrets.token_urlsafe(18); set_setting("sync_pairing_token", token)
    return token


def register_device(device_id: str, name: str, supplied_pairing_token: str) -> str:
    if not secrets.compare_digest(supplied_pairing_token, pairing_token()):
        raise PermissionError("Pairing-Code ist ungültig")
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC).isoformat()
    with connect() as connection:
        connection.execute(
            "INSERT INTO registered_devices(device_id, name, token_hash, registered_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET name=excluded.name, "
            "token_hash=excluded.token_hash, registered_at=excluded.registered_at, last_seen=excluded.last_seen",
            (device_id, name[:100], hashlib.sha256(token.encode()).hexdigest(), now, now),
        )
    return token


def authenticate_device(token: str) -> bool:
    if not token: return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect() as connection:
        row = connection.execute(
            "SELECT device_id FROM registered_devices WHERE token_hash = ?", (digest,)
        ).fetchone()
        if row:
            connection.execute("UPDATE registered_devices SET last_seen = ? WHERE device_id = ?",
                               (datetime.now(UTC).isoformat(), row["device_id"]))
    return bool(row)


def snapshot() -> dict:
    with connect() as connection:
        playlists = [dict(row) for row in connection.execute("SELECT * FROM playlists ORDER BY id")]
        media = [dict(row) for row in connection.execute("SELECT * FROM media_library ORDER BY id")]
        content = [dict(row) for row in connection.execute("SELECT * FROM content ORDER BY id")]
        referenced = referenced_media_files(connection)
    files = {}
    for name in sorted(referenced):
        path = media_dir() / name
        if path.is_file():
            files[name] = {"size": path.stat().st_size, "sha256": file_sha256(path)}
    return {"format": 1, "generated_at": datetime.now(UTC).isoformat(),
            "settings": {"screen_name": screen_name()}, "display_control": display_config(),
            "live": {"read_password": live.read_password()},
            "playlists": playlists, "media": media, "content": content, "files": files}


def _request_json(url: str, method: str = "GET", data: dict | None = None, token: str = "") -> dict:
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def sync_from_controller() -> dict:
    controller = (get_setting("controller_url") or get_setting("master_url") or "").rstrip("/") + "/"
    if not controller.startswith(("http://", "https://")): raise RuntimeError("Controller-Adresse fehlt")
    device_id = get_setting("device_id") or ""
    token = get_setting("sync_device_token") or ""
    if not token:
        pair = get_setting("sync_pairing_code") or ""
        response = _request_json(urljoin(controller, "api/sync/register"), "POST", {
            "device_id": device_id, "name": screen_name(), "pairing_token": pair,
        })
        token = response["device_token"]; set_setting("sync_device_token", token)
        set_setting("sync_pairing_code", "")
    data = _request_json(urljoin(controller, "api/sync/snapshot"), token=token)
    for filename, metadata in data.get("files", {}).items():
        if Path(filename).name != filename: continue
        target = media_dir() / filename
        if (target.is_file() and target.stat().st_size == metadata.get("size")
                and file_sha256(target) == metadata.get("sha256")):
            continue
        request = urllib.request.Request(urljoin(controller, f"api/sync/media/{filename}"),
                                         headers={"Authorization": f"Bearer {token}"})
        temporary = target.with_suffix(target.suffix + ".sync")
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024): output.write(chunk)
        digest = hashlib.sha256()
        with temporary.open("rb") as downloaded:
            while chunk := downloaded.read(1024 * 1024): digest.update(chunk)
        if temporary.stat().st_size != metadata.get("size") or digest.hexdigest() != metadata.get("sha256"):
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Mediendatei {filename} wurde unvollständig übertragen")
        temporary.replace(target)
        remember_sha256(target, digest.hexdigest())
    with connect() as connection:
        connection.execute("DELETE FROM content")
        connection.execute("DELETE FROM media_library")
        connection.execute("DELETE FROM playlists")
        for table in SYNCED_TABLES:
            # Controller und Display können unterschiedliche Versionen haben:
            # Spalten, die das Display noch nicht kennt, werden ignoriert.
            local_columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for row in data["media" if table == "media_library" else table]:
                columns = [column for column in row if column in local_columns]
                connection.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )
    removed_files = remove_unreferenced_media()
    set_setting("screen_name", data.get("settings", {}).get("screen_name", "Open Signage"))
    save_display_config(data.get("display_control") or display_config())
    read_password = (data.get("live") or {}).get("read_password")
    if read_password: set_setting("live_read_password", read_password)
    live.write_config()
    set_setting("sync_last_success", datetime.now(UTC).isoformat())
    set_setting("sync_last_error", "")
    return {"status": "synchronized", "at": get_setting("sync_last_success"), "removed_files": removed_files}


def remove_unreferenced_media() -> int:
    """Delete media files that the synchronized state no longer references."""
    with connect() as connection:
        referenced = referenced_media_files(connection)
    removed = 0
    for path in media_dir().iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink(missing_ok=True); removed += 1
    return removed


def safe_sync_from_controller() -> dict:
    try:
        return sync_from_controller()
    except (OSError, RuntimeError, KeyError, ValueError, sqlite3.Error, urllib.error.URLError) as error:
        set_setting("sync_last_error", str(error)[:500])
        return {"status": "offline", "error": str(error)}


# Backward-compatible aliases for integrations using the pre-0.13 names.
sync_from_master = sync_from_controller
safe_sync_from_master = safe_sync_from_controller
