from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from .auth import get_setting, screen_name, set_setting
from .database import connect, media_dir
from .display_control import display_config, save_display_config


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
    files = {}
    for item in media:
        for field in ("source", "original_source", "thumbnail_source"):
            source = item.get(field)
            if source:
                path = media_dir() / Path(source).name
                if path.is_file():
                    digest = hashlib.sha256()
                    with path.open("rb") as source_file:
                        while chunk := source_file.read(1024 * 1024): digest.update(chunk)
                    files[path.name] = {"size": path.stat().st_size, "sha256": digest.hexdigest()}
    return {"format": 1, "generated_at": datetime.now(UTC).isoformat(),
            "settings": {"screen_name": screen_name()}, "display_control": display_config(),
            "playlists": playlists, "media": media, "content": content, "files": files}


def _request_json(url: str, method: str = "GET", data: dict | None = None, token: str = "") -> dict:
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def sync_from_master() -> dict:
    master = (get_setting("master_url") or "").rstrip("/") + "/"
    if not master.startswith(("http://", "https://")): raise RuntimeError("Master-Adresse fehlt")
    device_id = get_setting("device_id") or ""
    token = get_setting("sync_device_token") or ""
    if not token:
        pair = get_setting("sync_pairing_code") or ""
        response = _request_json(urljoin(master, "api/sync/register"), "POST", {
            "device_id": device_id, "name": screen_name(), "pairing_token": pair,
        })
        token = response["device_token"]; set_setting("sync_device_token", token)
        set_setting("sync_pairing_code", "")
    data = _request_json(urljoin(master, "api/sync/snapshot"), token=token)
    for filename, metadata in data.get("files", {}).items():
        if Path(filename).name != filename: continue
        target = media_dir() / filename
        if target.is_file() and target.stat().st_size == metadata.get("size"):
            existing_digest = hashlib.sha256()
            with target.open("rb") as existing:
                while chunk := existing.read(1024 * 1024): existing_digest.update(chunk)
            if existing_digest.hexdigest() == metadata.get("sha256"): continue
        request = urllib.request.Request(urljoin(master, f"api/sync/media/{filename}"),
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
    with connect() as connection:
        connection.execute("DELETE FROM content")
        connection.execute("DELETE FROM media_library")
        connection.execute("DELETE FROM playlists")
        for table in ("playlists", "media_library", "content"):
            for row in data["media" if table == "media_library" else table]:
                columns = list(row)
                connection.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )
    set_setting("screen_name", data.get("settings", {}).get("screen_name", "Open Signage"))
    save_display_config(data.get("display_control") or display_config())
    set_setting("sync_last_success", datetime.now(UTC).isoformat())
    set_setting("sync_last_error", "")
    return {"status": "synchronized", "at": get_setting("sync_last_success")}


def safe_sync_from_master() -> dict:
    try:
        return sync_from_master()
    except (OSError, RuntimeError, KeyError, ValueError, urllib.error.URLError) as error:
        set_setting("sync_last_error", str(error)[:500])
        return {"status": "offline", "error": str(error)}
