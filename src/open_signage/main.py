from __future__ import annotations

import asyncio
import json
import hashlib
import os
import sqlite3
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import connect, data_dir, initialize, integrity_check_if_due, media_dir
from .display_control import (display_config, display_status, request_display_action,
                              save_display_config, schedule_analysis)
from .auth import (change_password, clear_login_failures, create_session, destroy_session,
                   ensure_login_allowed, get_setting, password_change_required, player_token,
                   record_login_failure, require_player, require_system_login, screen_name,
                   session_is_authenticated, set_setting, verify_password, device_mode)
from .application_update import request_update as request_application_update
from .application_update import update_status as application_update_status
from .backup import (automatic_backup_if_due, backup_dir, create_backup, list_backups,
                     restore_backup, validate_backup)
from .conversion_jobs import conversion_status, queue_conversion
from .media_probe import inspect_video, validate_video
from .upload_security import ensure_free_space, save_upload
from .image_processing import edit_image, optimize_image
from .video_processing import video_metadata, video_thumbnail
from .system_info import collect_system_info
from .system_update import request_update, update_status
from .sync import (authenticate_device, pairing_token, register_device, safe_sync_from_controller,
                   snapshot as sync_snapshot)
from .version import __version__

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    if not get_setting("device_role"):
        install_mode = os.environ.get("OPEN_SIGNAGE_MODE", "standalone")
        set_setting("device_role", install_mode if install_mode in {"standalone", "controller", "display"} else "standalone")
        controller_url = os.environ.get("OPEN_SIGNAGE_CONTROLLER_URL", "").strip()
        if controller_url: set_setting("controller_url", controller_url)
    device_mode()
    integrity_check_if_due()
    await asyncio.to_thread(automatic_backup_if_due)
    async def database_maintenance() -> None:
        ticks = 0
        while True:
            await asyncio.sleep(60)
            ticks += 1
            if device_mode() == "display": await asyncio.to_thread(safe_sync_from_controller)
            if ticks >= 24 * 60:
                ticks = 0
                await asyncio.to_thread(integrity_check_if_due)
                await asyncio.to_thread(automatic_backup_if_due)
    maintenance_task = asyncio.create_task(database_maintenance())
    try:
        yield
    finally:
        maintenance_task.cancel()


app = FastAPI(title="Open Signage", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class WebsiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    duration_seconds: int = Field(default=12, ge=1, le=86400)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class BackupCreate(BaseModel):
    include_media: bool = False


class ScreenSettings(BaseModel):
    screen_name: str = Field(min_length=1, max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class StreamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    duration_seconds: int = Field(default=3600, ge=1, le=86400)
    muted: bool = True


class ContentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    enabled: bool | None = None
    position: int | None = Field(default=None, ge=0)
    muted: bool | None = None
    play_to_end: bool | None = None
    schedule_start: str | None = Field(default=None, max_length=32)
    schedule_end: str | None = Field(default=None, max_length=32)
    schedule_weekdays: list[int] | None = None
    schedule_daily_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_daily_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    clear_schedule: bool | None = None


class LibraryPlaylistCreate(BaseModel):
    duration_seconds: int = Field(default=10, ge=1, le=86400)
    muted: bool = True
    play_to_end: bool = False


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PlaylistScheduleUpdate(BaseModel):
    schedule_enabled: bool = False
    schedule_start: str | None = Field(default=None, max_length=32)
    schedule_end: str | None = Field(default=None, max_length=32)
    schedule_weekdays: list[int] = Field(default_factory=list)
    schedule_daily_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_daily_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class DeviceSettings(BaseModel):
    role: str = Field(pattern=r"^(standalone|controller|display)$")
    controller_url: str = Field(default="", max_length=2048)
    pairing_code: str = Field(default="", max_length=200)
    current_password: str = Field(default="", max_length=200)


class SyncRegistration(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    pairing_token: str = Field(min_length=1, max_length=200)


class SystemAction(BaseModel):
    action: str = Field(pattern=r"^(restart_service|reboot|poweroff)$")


class DisplayScheduleEntry(BaseModel):
    weekday: int = Field(ge=0, le=6)
    on: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    off: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class DisplayControlSettings(BaseModel):
    cec_address: str = Field(default="0", pattern=r"^[0-9A-Fa-f]$")
    activate_source: bool = True
    fallback_hdmi_signal: bool = True
    resolution_mode: str = Field(default="1080p60", pattern=r"^(auto|1080p60|1080p50|720p60)$")
    schedule_enabled: bool = False
    schedule_entries: list[DisplayScheduleEntry] = Field(default_factory=list, max_length=100)


class DisplayAction(BaseModel):
    action: str = Field(pattern=r"^(on|off|status|resolution)$")


class ImageEdit(BaseModel):
    rotate: int = Field(default=0)
    crop_16_9: bool = False
    focus_x: int = Field(default=50, ge=0, le=100)
    focus_y: int = Field(default=50, ge=0, le=100)
    brightness: float = Field(default=1.0, ge=0.5, le=1.5)
    contrast: float = Field(default=1.0, ge=0.5, le=1.5)


class MediaLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)


class MediaBulkPlaylistCreate(BaseModel):
    media_ids: list[int] = Field(min_length=1, max_length=500)
    duration_seconds: int = Field(default=10, ge=1, le=86400)
    muted: bool = True
    play_to_end: bool = False


class PlayerHeartbeat(BaseModel):
    state: str = Field(pattern=r"^(playing|idle|buffering|error)$")
    content_id: int | None = None
    content_name: str | None = Field(default=None, max_length=200)
    error: str | None = Field(default=None, max_length=500)


def active_playlist_id(now: datetime | None = None) -> int:
    with connect() as connection:
        scheduled = connection.execute(
            "SELECT * FROM playlists WHERE schedule_enabled = 1 ORDER BY id DESC"
        ).fetchall()
        for candidate in scheduled:
            item = dict(candidate)
            item["schedule_weekdays"] = json.loads(item["schedule_weekdays"] or "[]")
            if scheduled_now(item, now):
                return item["id"]
        row = connection.execute(
            "SELECT id FROM playlists WHERE active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
    return row["id"] if row else 1


def serialize(row) -> dict:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["muted"] = bool(item["muted"])
    item["play_to_end"] = bool(item["play_to_end"])
    item["text_config"] = json.loads(item["text_config"]) if item.get("text_config") else None
    item["schedule_weekdays"] = (
        json.loads(item["schedule_weekdays"]) if item.get("schedule_weekdays") else []
    )
    return item


def scheduled_now(item: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now().astimezone()
    def schedule_moment(value: str) -> datetime:
        moment = datetime.fromisoformat(value)
        return moment.replace(tzinfo=now.tzinfo) if moment.tzinfo is None else moment

    if item.get("schedule_start") and now < schedule_moment(item["schedule_start"]):
        return False
    if item.get("schedule_end") and now > schedule_moment(item["schedule_end"]):
        return False
    weekdays = item.get("schedule_weekdays") or []
    if weekdays and now.weekday() not in weekdays:
        return False
    current_time = now.strftime("%H:%M")
    daily_start = item.get("schedule_daily_start")
    daily_end = item.get("schedule_daily_end")
    if daily_start and daily_end:
        if daily_start <= daily_end:
            return daily_start <= current_time <= daily_end
        return current_time >= daily_start or current_time <= daily_end
    if daily_start and current_time < daily_start:
        return False
    if daily_end and current_time > daily_end:
        return False
    return True


def get_content_or_404(content_id: int):
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM content WHERE id = ?", (content_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Inhalt nicht gefunden")
    return row


def get_library_media_or_404(media_id: int):
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM media_library WHERE id = ?", (media_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Medium nicht gefunden")
    return row


def serialize_library_media(row) -> dict:
    item = dict(row)
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    item["file_exists"] = local_media_exists(item.get("source"))
    paths = {media_dir() / Path(source).name for source in
             (item.get("source"), item.get("original_source"), item.get("thumbnail_source")) if source}
    item["storage_bytes"] = sum(path.stat().st_size for path in paths if path.is_file())
    return item


def local_media_exists(source: str | None) -> bool:
    if not source:
        return False
    parsed = urlparse(source)
    if parsed.scheme or parsed.netloc:
        return True
    return (media_dir() / Path(parsed.path).name).is_file()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024): digest.update(chunk)
    return digest.hexdigest()


def serialize_playlist(row) -> dict:
    item = dict(row)
    item["active"] = bool(item["active"])
    item["schedule_enabled"] = bool(item["schedule_enabled"])
    item["schedule_weekdays"] = json.loads(item["schedule_weekdays"] or "[]")
    item["effective"] = item["id"] == active_playlist_id()
    return item


@app.get("/", include_in_schema=False)
def admin_page():
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("@@VERSION@@", __version__), headers={"Cache-Control": "no-store"})


@app.get("/player", include_in_schema=False)
def player_page():
    html = (STATIC_DIR / "player.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("@@VERSION@@", __version__), headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.post("/api/player/heartbeat", status_code=204)
def player_heartbeat(payload: PlayerHeartbeat, _: None = Depends(require_player)):
    with connect() as connection:
        previous = connection.execute("SELECT error FROM player_status WHERE id = 1").fetchone()
        if payload.error and (not previous or previous["error"] != payload.error):
            connection.execute(
                "INSERT INTO player_events(created_at, level, message, content_name) VALUES (?, 'error', ?, ?)",
                (datetime.now(UTC).isoformat(), payload.error, payload.content_name),
            )
        connection.execute(
            """INSERT INTO player_status(id, last_seen, state, content_id, content_name, error)
               VALUES (1, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen,
               state = excluded.state, content_id = excluded.content_id,
               content_name = excluded.content_name, error = excluded.error""",
            (datetime.now(UTC).isoformat(), payload.state, payload.content_id, payload.content_name, payload.error),
        )


@app.get("/api/system/monitoring")
def monitoring(_: None = Depends(require_system_login)):
    info = collect_system_info()
    with connect() as connection:
        row = connection.execute("SELECT * FROM player_status WHERE id = 1").fetchone()
        events = connection.execute(
            "SELECT * FROM player_events ORDER BY id DESC LIMIT 20"
        ).fetchall()
    player = dict(row) if row else None
    if player:
        age = (datetime.now(UTC) - datetime.fromisoformat(player["last_seen"])).total_seconds()
        player["online"] = age < 25
        player["age_seconds"] = round(age)
    disk = info["disk"]
    free_ratio = (disk["total_bytes"] - disk["used_bytes"]) / disk["total_bytes"] if disk["total_bytes"] else 0
    warnings = []
    if free_ratio < 0.1:
        warnings.append("Weniger als 10 % Datenspeicher frei.")
    if info["temperature_celsius"] is not None and info["temperature_celsius"] >= 80:
        warnings.append("CPU-Temperatur beträgt mindestens 80 °C.")
    return {
        "player": player or {"online": False, "state": "unknown", "last_seen": None},
        "disk": disk,
        "temperature_celsius": info["temperature_celsius"],
        "warnings": warnings,
        "events": [dict(event) for event in events],
        "system_update": update_status(),
        "application_update": application_update_status(),
        "version": __version__,
    }


@app.get("/api/system/info")
def system_info(_: None = Depends(require_system_login)):
    return collect_system_info()


@app.get("/api/system/security-status")
def security_status(request: Request, _: None = Depends(require_system_login)):
    with connect() as connection:
        integrity_at = connection.execute(
            "SELECT value FROM maintenance_state WHERE key = 'last_integrity_check'"
        ).fetchone()
        integrity_result = connection.execute(
            "SELECT value FROM maintenance_state WHERE key = 'last_integrity_result'"
        ).fetchone()
    backups = list_backups()
    info = collect_system_info()
    checks = {
        "initial_password_changed": not password_change_required(),
        "player_token_available": bool(get_setting("player_token")),
        "database_integrity_ok": bool(integrity_result and json.loads(integrity_result["value"]) == ["ok"]),
        "backup_available": bool(backups),
        "storage_healthy": info["disk"]["used_bytes"] < info["disk"]["total_bytes"] * 0.9,
        "https": request.url.scheme == "https",
    }
    return {"checks": checks, "integrity_checked_at": integrity_at["value"] if integrity_at else None,
            "last_backup_at": backups[0]["created_at"] if backups else None,
            "warnings": [name for name, ok in checks.items() if not ok]}


@app.get("/api/system/update")
def get_system_update(_: None = Depends(require_system_login)):
    return update_status()


@app.post("/api/system/update", status_code=202)
def start_system_update(_: None = Depends(require_system_login)):
    try:
        return request_update()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/system/application-update")
def get_application_update(_: None = Depends(require_system_login)):
    return application_update_status()


@app.post("/api/system/application-update", status_code=202)
def start_application_update(_: None = Depends(require_system_login)):
    try:
        return request_application_update()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/settings")
def get_public_settings():
    return {"screen_name": screen_name()}


@app.get("/api/system/device")
def get_device_settings(_: None = Depends(require_system_login)):
    device_id = get_setting("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        set_setting("device_id", device_id)
    role = device_mode()
    controller_url = get_setting("controller_url") or get_setting("master_url", "") or ""
    if controller_url and not get_setting("controller_url"): set_setting("controller_url", controller_url)
    with connect() as connection:
        devices = [dict(row) for row in connection.execute(
            "SELECT device_id, name, registered_at, last_seen FROM registered_devices ORDER BY name"
        )] if role == "controller" else []
    last_success = get_setting("sync_last_success", "")
    last_error = get_setting("sync_last_error", "")
    return {"device_id": device_id, "role": role, "controller_url": controller_url,
            "pairing_code": pairing_token() if role == "controller" else "",
            "registered_devices": devices, "last_success": last_success, "last_error": last_error,
            "sync_status": "bereit" if role != "display" else
                (f"zuletzt {last_success}" if last_success else f"offline: {last_error}" if last_error else "noch nicht verbunden")}


@app.patch("/api/system/device")
def update_device_settings(payload: DeviceSettings, _: None = Depends(require_system_login)):
    if payload.role != device_mode() and not verify_password(payload.current_password):
        raise HTTPException(status_code=400, detail="Für den Moduswechsel ist das aktuelle Administratorpasswort erforderlich")
    if payload.role == "display" and not payload.controller_url.strip():
        raise HTTPException(status_code=422, detail="Für ein Display ist die Controller-Adresse erforderlich")
    set_setting("device_role", payload.role)
    set_setting("controller_url", payload.controller_url.strip())
    if payload.pairing_code.strip():
        set_setting("sync_pairing_code", payload.pairing_code.strip())
        set_setting("sync_device_token", "")
    return get_device_settings(_)


@app.post("/api/system/device/sync")
def sync_device_now(_: None = Depends(require_system_login)):
    if device_mode() != "display":
        raise HTTPException(status_code=409, detail="Nur ein Display kann vom Controller synchronisieren")
    result = safe_sync_from_controller()
    if result["status"] == "offline": raise HTTPException(status_code=502, detail=result["error"])
    return result


def require_sync_device(request: Request) -> None:
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    if not authenticate_device(token): raise HTTPException(status_code=401, detail="Ungültiger Geräte-Token")


@app.post("/api/sync/register")
def sync_register(payload: SyncRegistration):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    try:
        token = register_device(payload.device_id, payload.name, payload.pairing_token)
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return {"device_token": token}


@app.get("/api/sync/snapshot")
def get_sync_snapshot(_: None = Depends(require_sync_device)):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    return sync_snapshot()


@app.get("/api/sync/media/{filename}")
def get_sync_media(filename: str, _: None = Depends(require_sync_device)):
    if Path(filename).name != filename: raise HTTPException(status_code=404)
    path = media_dir() / filename
    if not path.is_file(): raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/api/system/storage")
def storage_status(_: None = Depends(require_system_login)):
    with connect() as connection:
        rows = connection.execute("SELECT * FROM media_library").fetchall()
        used = {row[0] for row in connection.execute("SELECT DISTINCT media_id FROM content WHERE media_id IS NOT NULL")}
    files = [path for path in media_dir().iterdir() if path.is_file()]
    known = {Path(source).name for row in rows for source in
             (row["source"], row["original_source"], row["thumbnail_source"]) if source}
    missing = [row["id"] for row in rows if not local_media_exists(row["source"])]
    orphan = [path for path in files if path.name not in known]
    hashes: dict[str, list[int]] = {}
    for row in rows:
        path = media_dir() / Path(row["source"]).name
        if path.is_file():
            digest = file_sha256(path)
            hashes.setdefault(digest, []).append(row["id"])
    duplicates = [ids for ids in hashes.values() if len(ids) > 1]
    return {"media_count": len(rows), "unused_media_count": sum(row["id"] not in used for row in rows),
            "media_bytes": sum(path.stat().st_size for path in files), "file_count": len(files),
            "missing_media_ids": missing, "orphan_file_count": len(orphan),
            "orphan_bytes": sum(path.stat().st_size for path in orphan), "duplicate_groups": duplicates}


@app.get("/api/system/backups")
def get_backups(_: None = Depends(require_system_login)):
    return list_backups()


@app.post("/api/system/backups", status_code=201)
def start_backup(payload: BackupCreate, _: None = Depends(require_system_login)):
    try:
        return create_backup(include_media=payload.include_media)
    except (OSError, RuntimeError) as error:
        raise HTTPException(status_code=500, detail=f"Backup fehlgeschlagen: {error}") from error


@app.get("/api/system/backups/{filename}")
def download_backup(filename: str, _: None = Depends(require_system_login)):
    if Path(filename).name != filename:
        raise HTTPException(status_code=404)
    path = backup_dir() / filename
    if not path.is_file(): raise HTTPException(status_code=404, detail="Backup nicht gefunden")
    return FileResponse(path, filename=filename, media_type="application/zip")


@app.post("/api/system/backups/restore")
def restore_uploaded_backup(
    file: Annotated[UploadFile, File()], _: None = Depends(require_system_login)
):
    temporary = data_dir() / ".restore-upload.zip"
    try:
        size = 0
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > 5 * 1024 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Backup ist zu groß")
                output.write(chunk)
        validate_backup(temporary)
        restore_backup(temporary)
    except (ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise HTTPException(status_code=415, detail=f"Ungültiges Backup: {error}") from error
    finally:
        file.file.close(); temporary.unlink(missing_ok=True)
    return {"restored": True, "message": "Backup wiederhergestellt. Anwendung bitte neu starten."}


@app.post("/api/system/storage/cleanup")
def cleanup_storage(_: None = Depends(require_system_login)):
    removed_media = 0
    removed_files = 0
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM media_library WHERE id NOT IN (SELECT DISTINCT media_id FROM content WHERE media_id IS NOT NULL)"
        ).fetchall()
        for row in rows:
            for source in {row["source"], row["original_source"], row["thumbnail_source"]}:
                if source:
                    path = media_dir() / Path(source).name
                    if path.exists(): path.unlink(); removed_files += 1
            connection.execute("DELETE FROM media_library WHERE id = ?", (row["id"],))
            removed_media += 1
    return {"removed_media": removed_media, "removed_files": removed_files}


@app.post("/api/system/storage/orphans/cleanup")
def cleanup_orphan_files(_: None = Depends(require_system_login)):
    with connect() as connection:
        rows = connection.execute("SELECT source, original_source, thumbnail_source FROM media_library").fetchall()
    known = {Path(source).name for row in rows for source in row if source}
    removed = 0; removed_bytes = 0
    for path in media_dir().iterdir():
        if path.is_file() and path.name not in known:
            removed_bytes += path.stat().st_size; path.unlink(); removed += 1
    return {"removed_files": removed, "removed_bytes": removed_bytes}


@app.post("/api/system/action", status_code=202)
def request_system_action(payload: SystemAction, _: None = Depends(require_system_login)):
    (data_dir() / "system-action-request").write_text(payload.action, encoding="utf-8")
    return {"queued": True, "action": payload.action}


@app.get("/api/system/display-control")
def get_display_control(_: None = Depends(require_system_login)):
    config = display_config()
    return {"config": config, "status": display_status(), "schedule": schedule_analysis(config)}


@app.patch("/api/system/display-control")
def update_display_control(payload: DisplayControlSettings, _: None = Depends(require_system_login)):
    if any(entry.on == entry.off for entry in payload.schedule_entries):
        raise HTTPException(status_code=422, detail="Ein- und Ausschaltzeit müssen unterschiedlich sein")
    config = payload.model_dump()
    config["cec_address"] = config["cec_address"].upper()
    config["schedule_entries"] = sorted(
        config["schedule_entries"], key=lambda entry: (entry["weekday"], entry["on"], entry["off"])
    )
    save_display_config(config)
    request_display_action("resolution")
    return {"config": config, "status": display_status(), "schedule": schedule_analysis(config)}


@app.post("/api/system/display-control/action", status_code=202)
def start_display_action(payload: DisplayAction, _: None = Depends(require_system_login)):
    request_display_action(payload.action)
    return {"queued": True, "action": payload.action}


@app.get("/api/system/session")
def system_session(request: Request):
    if not session_is_authenticated(request):
        return {"authenticated": False}
    return {"authenticated": True, "screen_name": screen_name(), "device_mode": device_mode(),
            "password_change_required": password_change_required()}


@app.post("/api/system/login")
def system_login(payload: LoginRequest, request: Request, response: Response):
    ensure_login_allowed(request)
    if not verify_password(payload.password):
        record_login_failure(request)
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    clear_login_failures(request)
    create_session(response)
    return {"authenticated": True, "screen_name": screen_name(),
            "password_change_required": password_change_required()}


@app.post("/api/system/logout", status_code=204)
def system_logout(request: Request, response: Response):
    destroy_session(request, response)


@app.patch("/api/system/settings")
def update_system_settings(payload: ScreenSettings, _: None = Depends(require_system_login)):
    name = payload.screen_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Der Bildschirmname darf nicht leer sein")
    set_setting("screen_name", name)
    return {"screen_name": name}


@app.post("/api/system/password")
def update_system_password(payload: PasswordChange, response: Response, _: None = Depends(require_system_login)):
    if not verify_password(payload.current_password):
        raise HTTPException(status_code=400, detail="Das aktuelle Passwort ist falsch")
    change_password(payload.new_password, response)
    return {"changed": True}


def content_rows(enabled_only: bool = False) -> list[dict]:
    query = "SELECT * FROM content WHERE playlist_id = ?"
    params: tuple = (active_playlist_id(),)
    if enabled_only:
        query += " AND enabled = ?"
        params = (*params, 1)
    query += " ORDER BY position, id"
    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    items = [serialize(row) for row in rows]
    if not enabled_only:
        return items
    return [
        item for item in items
        if scheduled_now(item)
        and (item["kind"] not in {"image", "video", "pdf", "text"} or local_media_exists(item["source"]))
    ]


@app.get("/api/player/bootstrap")
def player_bootstrap(request: Request):
    if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        require_system_login(request)
    return {"token": player_token()}


@app.get("/api/player/content")
def player_content(_: None = Depends(require_player)):
    return content_rows(enabled_only=True)


@app.get("/api/playlists")
def list_playlists(_: None = Depends(require_system_login)):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT playlists.*, COUNT(content.id) AS content_count
            FROM playlists LEFT JOIN content ON content.playlist_id = playlists.id
            GROUP BY playlists.id ORDER BY playlists.name COLLATE NOCASE
            """
        ).fetchall()
    return [serialize_playlist(row) for row in rows]


@app.patch("/api/playlists/{playlist_id}/schedule")
def update_playlist_schedule(playlist_id: int, payload: PlaylistScheduleUpdate, _: None = Depends(require_system_login)):
    if any(day < 0 or day > 6 for day in payload.schedule_weekdays):
        raise HTTPException(status_code=422, detail="Ungültiger Wochentag")
    for value in (payload.schedule_start, payload.schedule_end):
        if value:
            try: datetime.fromisoformat(value)
            except ValueError as error: raise HTTPException(status_code=422, detail="Ungültiges Datum") from error
    with connect() as connection:
        if not connection.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Playlist nicht gefunden")
        connection.execute("""UPDATE playlists SET schedule_enabled=?, schedule_start=?, schedule_end=?,
            schedule_weekdays=?, schedule_daily_start=?, schedule_daily_end=? WHERE id=?""",
            (int(payload.schedule_enabled), payload.schedule_start, payload.schedule_end,
             json.dumps(sorted(set(payload.schedule_weekdays))), payload.schedule_daily_start,
             payload.schedule_daily_end, playlist_id))
    with connect() as connection:
        return serialize_playlist(connection.execute("SELECT playlists.*, (SELECT COUNT(*) FROM content WHERE playlist_id=playlists.id) content_count FROM playlists WHERE id=?", (playlist_id,)).fetchone())


@app.post("/api/playlists", status_code=201)
def create_playlist(payload: PlaylistCreate, _: None = Depends(require_system_login)):
    try:
        with connect() as connection:
            cursor = connection.execute(
                "INSERT INTO playlists(name, active) VALUES (?, 0)", (payload.name.strip(),)
            )
            playlist_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Eine Playlist mit diesem Namen existiert bereits") from error
    return {"id": playlist_id, "name": payload.name.strip(), "active": False, "content_count": 0}


@app.post("/api/playlists/{playlist_id}/activate")
def activate_playlist(playlist_id: int, _: None = Depends(require_system_login)):
    with connect() as connection:
        exists = connection.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Playlist nicht gefunden")
        connection.execute("UPDATE playlists SET active = 0")
        connection.execute("UPDATE playlists SET active = 1 WHERE id = ?", (playlist_id,))
    return {"active_playlist_id": playlist_id}


@app.delete("/api/playlists/{playlist_id}", status_code=204)
def delete_playlist(playlist_id: int, _: None = Depends(require_system_login)):
    with connect() as connection:
        row = connection.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playlist nicht gefunden")
        if connection.execute("SELECT COUNT(*) FROM playlists").fetchone()[0] <= 1:
            raise HTTPException(status_code=409, detail="Die letzte Playlist kann nicht gelöscht werden")
        if row["active"]:
            raise HTTPException(status_code=409, detail="Die aktive Playlist kann nicht gelöscht werden")
        media_rows = connection.execute(
            "SELECT source, media_id, kind FROM content WHERE playlist_id = ?", (playlist_id,)
        ).fetchall()
        connection.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    for media in media_rows:
        if media["media_id"] is None and media["kind"] in {"image", "video", "pdf", "text"}:
            (media_dir() / Path(media["source"]).name).unlink(missing_ok=True)


@app.get("/api/content")
def list_content(_: None = Depends(require_system_login)):
    return content_rows()


@app.post("/api/content/upload", status_code=201)
def upload_content(
    file: Annotated[UploadFile, File()],
    duration_seconds: Annotated[int, Form(ge=1, le=86400)] = 10,
    muted: Annotated[bool, Form()] = True,
    play_to_end: Annotated[bool, Form()] = False,
    _: None = Depends(require_system_login),
):
    try:
        destination, kind, size = save_upload(file, media_dir(), {"image", "video", "pdf"})
    except HTTPException as error:
        if error.status_code == 415:
            error.detail = "Erlaubt sind echte JPG-, PNG-, WebP-, GIF-, MP4-, WebM- und PDF-Dateien."
        raise
    stored_name = destination.name
    try:
        compatibility = validate_video(destination) if kind == "video" else None
    except ValueError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="Video konnte nicht vollständig geprüft werden.") from error
    source = f"/media/{stored_name}"
    original_source = None
    thumbnail_source = None
    metadata = {}
    if kind == "image":
        try:
            processed = optimize_image(destination, media_dir())
        except Exception as error:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=415, detail="Bild konnte nicht verarbeitet werden") from error
        source = processed["source"]
        original_source = f"/media/{stored_name}"
        thumbnail_source = processed["thumbnail_source"]
        metadata = {"width": processed["width"], "height": processed["height"]}
    elif kind == "video":
        try:
            metadata = video_metadata(destination)
            thumbnail_source = video_thumbnail(destination, media_dir())
        except Exception:
            # Die bereits bestehende Kompatibilitätsprüfung liefert dem Nutzer
            # die konkrete Warnung; der Upload selbst bleibt weiterhin möglich.
            metadata = {}
            thumbnail_source = None

    playlist_id = active_playlist_id()
    with connect() as connection:
        media_id = None
        if kind in {"image", "video"}:
            media_cursor = connection.execute(
                """INSERT INTO media_library(
                    name, kind, source, size_bytes, original_source, thumbnail_source,
                    width, height, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    Path(file.filename or stored_name).name,
                    kind,
                    source,
                    size,
                    original_source,
                    thumbnail_source,
                    metadata.get("width"),
                    metadata.get("height"),
                    json.dumps(metadata),
                ),
            )
            media_id = media_cursor.lastrowid
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(
                name, kind, source, duration_seconds, position, playlist_id,
                muted, play_to_end, media_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                Path(file.filename or stored_name).name,
                kind,
                source,
                duration_seconds,
                position,
                playlist_id,
                int(muted),
                int(play_to_end),
                media_id,
            ),
        )
        content_id = cursor.lastrowid
    response = serialize(get_content_or_404(content_id))
    if compatibility is not None:
        response["compatibility"] = compatibility
    return response


def save_text_background(file: UploadFile, allow_video: bool = False) -> str:
    allowed = {"image", "video"} if allow_video else {"image"}
    try:
        destination, kind, _ = save_upload(file, media_dir(), allowed)
        if kind == "video":
            validate_video(destination)
    except ValueError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="Video konnte nicht vollständig geprüft werden.") from error
    return f"/media/{destination.name}"


@app.get("/api/media-library")
def list_media_library(_: None = Depends(require_system_login)):
    with connect() as connection:
        rows = connection.execute(
            """SELECT media_library.*, COUNT(content.id) AS usage_count
               FROM media_library LEFT JOIN content ON content.media_id = media_library.id
               GROUP BY media_library.id ORDER BY created_at DESC, media_library.id DESC"""
        ).fetchall()
    return [serialize_library_media(row) for row in rows]


@app.post("/api/media-library", status_code=201)
def upload_library_media(
    file: Annotated[UploadFile, File()],
    _: None = Depends(require_system_login),
):
    try:
        destination, kind, size = save_upload(file, media_dir(), {"image", "video"})
    except HTTPException as error:
        if error.status_code == 415:
            error.detail = "Für die Mediathek sind echte JPG-, PNG-, WebP-, GIF-, MP4- und WebM-Dateien erlaubt."
        raise
    stored_name = destination.name
    try:
        compatibility = validate_video(destination) if kind == "video" else None
    except ValueError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="Video konnte nicht vollständig geprüft werden.") from error
    processed = None
    metadata = {}
    thumbnail_source = None
    if kind == "image":
        try:
            processed = optimize_image(destination, media_dir())
        except Exception as error:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=415, detail="Bild konnte nicht verarbeitet werden") from error
        metadata = {"width": processed["width"], "height": processed["height"]}
    elif kind == "video":
        try:
            metadata = video_metadata(destination)
            thumbnail_source = video_thumbnail(destination, media_dir())
        except Exception as error:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=415, detail="Video konnte nicht verarbeitet werden") from error
    source = processed["source"] if processed else f"/media/{stored_name}"
    with connect() as connection:
        cursor = connection.execute(
            """INSERT INTO media_library(
                name, kind, source, size_bytes, original_source, thumbnail_source, width, height, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                Path(file.filename or stored_name).name, kind, source, size,
                f"/media/{stored_name}" if processed else None,
                processed["thumbnail_source"] if processed else thumbnail_source,
                metadata.get("width"), metadata.get("height"),
                json.dumps(metadata),
            ),
        )
        media_id = cursor.lastrowid
    response = serialize_library_media(get_library_media_or_404(media_id))
    if compatibility is not None:
        response["compatibility"] = compatibility
    return response


@app.patch("/api/media-library/{media_id}")
def update_library_media(
    media_id: int,
    payload: MediaLibraryUpdate,
    _: None = Depends(require_system_login),
):
    get_library_media_or_404(media_id)
    values = payload.model_dump(exclude_none=True)
    if not values:
        return serialize_library_media(get_library_media_or_404(media_id))
    values = {key: value.strip() for key, value in values.items()}
    with connect() as connection:
        connection.execute(
            f"UPDATE media_library SET {', '.join(f'{key} = ?' for key in values)} WHERE id = ?",
            (*values.values(), media_id),
        )
        if "name" in values:
            connection.execute(
                "UPDATE content SET name = ? WHERE media_id = ?", (values["name"], media_id)
            )
    return serialize_library_media(get_library_media_or_404(media_id))


@app.post("/api/media-library/{media_id}/replace")
def replace_library_file(
    media_id: int, file: Annotated[UploadFile, File()], _: None = Depends(require_system_login)
):
    media = get_library_media_or_404(media_id)
    destination, kind, size = save_upload(file, media_dir(), {media["kind"]})
    processed = None; metadata = {}; thumbnail = None
    try:
        if kind == "image":
            processed = optimize_image(destination, media_dir())
            metadata = {"width": processed["width"], "height": processed["height"]}
        else:
            compatibility = validate_video(destination)
            metadata = video_metadata(destination)
            thumbnail = video_thumbnail(destination, media_dir())
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="Ersatzdatei konnte nicht verarbeitet werden") from error
    source = processed["source"] if processed else f"/media/{destination.name}"
    original = f"/media/{destination.name}" if processed else None
    thumbnail = processed["thumbnail_source"] if processed else thumbnail
    old = {media["source"], media["original_source"], media["thumbnail_source"]}
    with connect() as connection:
        connection.execute(
            "UPDATE media_library SET source=?, size_bytes=?, original_source=?, thumbnail_source=?, "
            "width=?, height=?, metadata_json=? WHERE id=?",
            (source, size, original, thumbnail, metadata.get("width"), metadata.get("height"),
             json.dumps(metadata), media_id),
        )
        connection.execute("UPDATE content SET source=? WHERE media_id=?", (source, media_id))
    for old_source in old:
        if old_source and old_source not in {source, original, thumbnail}:
            (media_dir() / Path(old_source).name).unlink(missing_ok=True)
    result = serialize_library_media(get_library_media_or_404(media_id))
    if kind == "video": result["compatibility"] = compatibility
    return result


@app.post("/api/media-library/bulk-playlist", status_code=201)
def add_media_bulk_to_playlist(
    payload: MediaBulkPlaylistCreate,
    _: None = Depends(require_system_login),
):
    playlist_id = active_playlist_id()
    created = []
    with connect() as connection:
        for media_id in dict.fromkeys(payload.media_ids):
            media = connection.execute("SELECT * FROM media_library WHERE id = ?", (media_id,)).fetchone()
            if not media:
                raise HTTPException(status_code=404, detail=f"Medium {media_id} nicht gefunden")
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM content WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()[0]
            cursor = connection.execute(
                """INSERT INTO content(name, kind, source, duration_seconds, position, media_id, playlist_id, muted, play_to_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (media["name"], media["kind"], media["source"], payload.duration_seconds, position, media_id, playlist_id, int(payload.muted), int(payload.play_to_end)),
            )
            created.append(cursor.lastrowid)
    return {"created_ids": created}


@app.post("/api/media-library/{media_id}/transcode", status_code=202)
def convert_library_video(media_id: int, _: None = Depends(require_system_login)):
    media = get_library_media_or_404(media_id)
    if media["kind"] != "video":
        raise HTTPException(status_code=422, detail="Nur Videos können konvertiert werden")
    original_source = media["original_source"] or media["source"]
    source_path = media_dir() / Path(original_source).name
    try:
        ensure_free_space(media_dir(), source_path.stat().st_size)
    except (OSError, HTTPException) as error:
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=404, detail="Videoquelldatei fehlt") from error
    job_id = queue_conversion(media_id, source_path, original_source)
    return {"job_id": job_id, "status": "queued", "message": "Konvertierung wurde gestartet."}


@app.get("/api/conversions/{job_id}")
def get_conversion(job_id: str, _: None = Depends(require_system_login)):
    job = conversion_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Konvertierungsauftrag nicht gefunden")
    if job["status"] == "completed":
        job["media"] = serialize_library_media(get_library_media_or_404(job["media_id"]))
    return job


@app.post("/api/media-library/{media_id}/edit-image")
def process_library_image(
    media_id: int,
    payload: ImageEdit,
    _: None = Depends(require_system_login),
):
    media = get_library_media_or_404(media_id)
    if media["kind"] != "image":
        raise HTTPException(status_code=422, detail="Nur Bilder können bearbeitet werden")
    if payload.rotate not in {0, 90, 180, 270}:
        raise HTTPException(status_code=422, detail="Ungültige Drehung")
    original_source = media["original_source"] or media["source"]
    original = media_dir() / Path(original_source).name
    try:
        processed = edit_image(original, media_dir(), **payload.model_dump())
    except Exception as error:
        raise HTTPException(status_code=500, detail="Bildbearbeitung fehlgeschlagen") from error
    old_files = [media["source"], media["thumbnail_source"]]
    with connect() as connection:
        connection.execute(
            """UPDATE media_library
               SET source = ?, thumbnail_source = ?, width = ?, height = ? WHERE id = ?""",
            (processed["source"], processed["thumbnail_source"], processed["width"], processed["height"], media_id),
        )
        connection.execute(
            "UPDATE content SET source = ? WHERE media_id = ?",
            (processed["source"], media_id),
        )
    for old in old_files:
        if old and old != original_source:
            (media_dir() / Path(old).name).unlink(missing_ok=True)
    return serialize_library_media(get_library_media_or_404(media_id))


@app.post("/api/media-library/{media_id}/playlist", status_code=201)
def add_library_media_to_playlist(
    media_id: int,
    payload: LibraryPlaylistCreate,
    _: None = Depends(require_system_login),
):
    media = get_library_media_or_404(media_id)
    playlist_id = active_playlist_id()
    with connect() as connection:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(name, kind, source, duration_seconds, position, media_id, playlist_id, muted, play_to_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (media["name"], media["kind"], media["source"], payload.duration_seconds, position, media_id, playlist_id, int(payload.muted), int(payload.play_to_end)),
        )
        content_id = cursor.lastrowid
    return serialize(get_content_or_404(content_id))


@app.delete("/api/media-library/{media_id}", status_code=204)
def delete_library_media(media_id: int, _: None = Depends(require_system_login)):
    media = get_library_media_or_404(media_id)
    with connect() as connection:
        used = connection.execute(
            "SELECT COUNT(*) FROM content WHERE media_id = ?", (media_id,)
        ).fetchone()[0]
        if used:
            raise HTTPException(
                status_code=409,
                detail="Das Medium wird noch in der Playlist oder einem Freitext verwendet.",
            )
        connection.execute("DELETE FROM media_library WHERE id = ?", (media_id,))
    for source in {media["source"], media["original_source"], media["thumbnail_source"]}:
        if source:
            (media_dir() / Path(source).name).unlink(missing_ok=True)


def text_configuration(
    headline: str,
    subheadline: str,
    body: str,
    shadow_box: bool,
    shadow_intensity: str,
    text_align: str,
    vertical_position: str,
    text_color: str,
    accent_color: str,
    font_size: str,
    font_family: str,
    background_dim: int,
    focus_x: int,
    focus_y: int,
    template_style: str,
    logo_source: str | None = None,
) -> str:
    if not any(value.strip() for value in (headline, subheadline, body)):
        raise HTTPException(status_code=422, detail="Mindestens ein Textfeld muss ausgefüllt sein")
    if shadow_intensity not in {"light", "medium", "dark"}:
        raise HTTPException(status_code=422, detail="Ungültige Schattenbox-Intensität")
    allowed = {
        "text_align": (text_align, {"left", "center", "right"}),
        "vertical_position": (vertical_position, {"top", "center", "bottom"}),
        "font_size": (font_size, {"small", "medium", "large"}),
        "font_family": (font_family, {"sans", "serif", "mono"}),
        "template_style": (template_style, {"standard", "elegant", "alert"}),
    }
    if any(value not in choices for value, choices in allowed.values()):
        raise HTTPException(status_code=422, detail="Ungültige Freitext-Gestaltung")
    if not all(value.startswith("#") and len(value) == 7 for value in (text_color, accent_color)):
        raise HTTPException(status_code=422, detail="Ungültige Farbe")
    if not 0 <= background_dim <= 80 or not 0 <= focus_x <= 100 or not 0 <= focus_y <= 100:
        raise HTTPException(status_code=422, detail="Ungültiger Bildwert")
    return json.dumps(
        {
            "headline": headline.strip(),
            "subheadline": subheadline.strip(),
            "body": body.strip(),
            "shadow_box": shadow_box,
            "shadow_intensity": shadow_intensity,
            "text_align": text_align,
            "vertical_position": vertical_position,
            "text_color": text_color,
            "accent_color": accent_color,
            "font_size": font_size,
            "font_family": font_family,
            "background_dim": background_dim,
            "focus_x": focus_x,
            "focus_y": focus_y,
            "template_style": template_style,
            "logo_source": logo_source,
        },
        ensure_ascii=False,
    )


@app.post("/api/content/text", status_code=201)
def create_text_content(
    name: Annotated[str, Form(min_length=1, max_length=200)],
    headline: Annotated[str, Form(max_length=200)] = "",
    subheadline: Annotated[str, Form(max_length=300)] = "",
    body: Annotated[str, Form(max_length=4000)] = "",
    shadow_box: Annotated[bool, Form()] = False,
    shadow_intensity: Annotated[str, Form()] = "medium",
    text_align: Annotated[str, Form()] = "left",
    vertical_position: Annotated[str, Form()] = "center",
    text_color: Annotated[str, Form()] = "#ffffff",
    accent_color: Annotated[str, Form()] = "#39d98a",
    font_size: Annotated[str, Form()] = "medium",
    font_family: Annotated[str, Form()] = "sans",
    background_dim: Annotated[int, Form(ge=0, le=80)] = 0,
    focus_x: Annotated[int, Form(ge=0, le=100)] = 50,
    focus_y: Annotated[int, Form(ge=0, le=100)] = 50,
    template_style: Annotated[str, Form()] = "standard",
    duration_seconds: Annotated[int, Form(ge=1, le=86400)] = 12,
    background: Annotated[UploadFile | None, File()] = None,
    library_media_id: Annotated[int | None, Form()] = None,
    logo: Annotated[UploadFile | None, File()] = None,
    _: None = Depends(require_system_login),
):
    config = text_configuration(
        headline, subheadline, body, shadow_box, shadow_intensity, text_align,
        vertical_position, text_color, accent_color, font_size, font_family,
        background_dim, focus_x, focus_y, template_style, None,
    )
    logo_source = save_text_background(logo) if logo and logo.filename else None
    if logo_source:
        config_data = json.loads(config)
        config_data["logo_source"] = logo_source
        config = json.dumps(config_data, ensure_ascii=False)
    library_media = get_library_media_or_404(library_media_id) if library_media_id else None
    if library_media and library_media["kind"] not in {"image", "video"}:
        raise HTTPException(status_code=422, detail="Als Freitext-Hintergrund ist nur ein Bild oder Video möglich")
    if background and background.filename:
        source = save_text_background(background, True)
        background_kind = "video" if Path(source).suffix in {".mp4", ".webm"} else "image"
        library_media_id = None
    elif library_media:
        source = library_media["source"]
        background_kind = library_media["kind"]
    else:
        raise HTTPException(status_code=422, detail="Bitte ein Hintergrundbild oder -video auswählen")
    config_data = json.loads(config)
    config_data["background_kind"] = background_kind
    config = json.dumps(config_data, ensure_ascii=False)
    try:
        playlist_id = active_playlist_id()
        with connect() as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM content WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()[0]
            cursor = connection.execute(
                """
                INSERT INTO content(name, kind, source, duration_seconds, position, text_config, media_id, playlist_id)
                VALUES (?, 'text', ?, ?, ?, ?, ?, ?)
                """,
                (name.strip(), source, duration_seconds, position, config, library_media_id, playlist_id),
            )
            content_id = cursor.lastrowid
    except Exception:
        if not library_media_id:
            (media_dir() / Path(source).name).unlink(missing_ok=True)
        if logo_source:
            (media_dir() / Path(logo_source).name).unlink(missing_ok=True)
        raise
    return serialize(get_content_or_404(content_id))


@app.post("/api/content/{content_id}/text")
def edit_text_content(
    content_id: int,
    name: Annotated[str, Form(min_length=1, max_length=200)],
    headline: Annotated[str, Form(max_length=200)] = "",
    subheadline: Annotated[str, Form(max_length=300)] = "",
    body: Annotated[str, Form(max_length=4000)] = "",
    shadow_box: Annotated[bool, Form()] = False,
    shadow_intensity: Annotated[str, Form()] = "medium",
    text_align: Annotated[str, Form()] = "left",
    vertical_position: Annotated[str, Form()] = "center",
    text_color: Annotated[str, Form()] = "#ffffff",
    accent_color: Annotated[str, Form()] = "#39d98a",
    font_size: Annotated[str, Form()] = "medium",
    font_family: Annotated[str, Form()] = "sans",
    background_dim: Annotated[int, Form(ge=0, le=80)] = 0,
    focus_x: Annotated[int, Form(ge=0, le=100)] = 50,
    focus_y: Annotated[int, Form(ge=0, le=100)] = 50,
    template_style: Annotated[str, Form()] = "standard",
    duration_seconds: Annotated[int, Form(ge=1, le=86400)] = 12,
    background: Annotated[UploadFile | None, File()] = None,
    library_media_id: Annotated[int | None, Form()] = None,
    logo: Annotated[UploadFile | None, File()] = None,
    remove_logo: Annotated[bool, Form()] = False,
    _: None = Depends(require_system_login),
):
    row = get_content_or_404(content_id)
    if row["kind"] != "text":
        raise HTTPException(status_code=422, detail="Dieser Inhalt ist kein Freitext")
    old_config = json.loads(row["text_config"] or "{}")
    old_logo = old_config.get("logo_source")
    logo_source = None if remove_logo else old_logo
    config = text_configuration(
        headline, subheadline, body, shadow_box, shadow_intensity, text_align,
        vertical_position, text_color, accent_color, font_size, font_family,
        background_dim, focus_x, focus_y, template_style, logo_source,
    )
    new_logo = save_text_background(logo) if logo and logo.filename else None
    if new_logo:
        logo_source = new_logo
        config_data = json.loads(config)
        config_data["logo_source"] = logo_source
        config = json.dumps(config_data, ensure_ascii=False)
    source = row["source"]
    selected_media = get_library_media_or_404(library_media_id) if library_media_id else None
    if selected_media and selected_media["kind"] not in {"image", "video"}:
        raise HTTPException(status_code=422, detail="Als Freitext-Hintergrund ist nur ein Bild oder Video möglich")
    new_source = save_text_background(background, True) if background and background.filename else None
    uploaded_kind = (
        "video" if new_source and Path(new_source).suffix in {".mp4", ".webm"} else "image"
    ) if new_source else None
    if new_source:
        source = new_source
        background_kind = uploaded_kind
        library_media_id = None
    elif selected_media:
        source = selected_media["source"]
        background_kind = selected_media["kind"]
    else:
        library_media_id = row["media_id"]
        background_kind = old_config.get("background_kind", "image")
    config_data = json.loads(config)
    config_data["background_kind"] = background_kind
    config = json.dumps(config_data, ensure_ascii=False)
    try:
        with connect() as connection:
            connection.execute(
                """
                UPDATE content
                SET name = ?, source = ?, duration_seconds = ?, text_config = ?, media_id = ?
                WHERE id = ?
                """,
                (name.strip(), source, duration_seconds, config, library_media_id, content_id),
            )
    except Exception:
        if new_source:
            (media_dir() / Path(new_source).name).unlink(missing_ok=True)
        if new_logo:
            (media_dir() / Path(new_logo).name).unlink(missing_ok=True)
        raise
    if source != row["source"] and row["media_id"] is None:
        (media_dir() / Path(row["source"]).name).unlink(missing_ok=True)
    if old_logo and old_logo != logo_source:
        (media_dir() / Path(old_logo).name).unlink(missing_ok=True)
    return serialize(get_content_or_404(content_id))


@app.post("/api/content/website", status_code=201)
def create_website(payload: WebsiteCreate, _: None = Depends(require_system_login)):
    parsed = urlparse(payload.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Ungültige HTTP(S)-Adresse")
    playlist_id = active_playlist_id()
    with connect() as connection:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(name, kind, source, duration_seconds, position, playlist_id)
            VALUES (?, 'website', ?, ?, ?, ?)
            """,
            (payload.name, payload.url, payload.duration_seconds, position, playlist_id),
        )
        content_id = cursor.lastrowid
    return serialize(get_content_or_404(content_id))


def normalize_owncast_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Ungültige HTTP(S)-Adresse")

    path = parsed.path.rstrip("/")
    if path.endswith("/embed/video"):
        path = path.removesuffix("/embed/video")
    elif path.endswith("/hls/stream.m3u8"):
        path = path.removesuffix("/hls/stream.m3u8")
    return parsed._replace(path=f"{path}/hls/stream.m3u8", query="", fragment="").geturl()


@app.post("/api/content/stream", status_code=201)
def create_stream(payload: StreamCreate, _: None = Depends(require_system_login)):
    stream_url = normalize_owncast_url(payload.url)
    playlist_id = active_playlist_id()
    with connect() as connection:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(
                name, kind, source, duration_seconds, position, muted, playlist_id
            )
            VALUES (?, 'stream', ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                stream_url,
                payload.duration_seconds,
                position,
                int(payload.muted),
                playlist_id,
            ),
        )
        content_id = cursor.lastrowid
    return serialize(get_content_or_404(content_id))


@app.patch("/api/content/{content_id}")
def update_content(content_id: int, payload: ContentUpdate, _: None = Depends(require_system_login)):
    get_content_or_404(content_id)
    values = payload.model_dump(exclude_none=True)
    schedule_fields = {
        "schedule_start", "schedule_end", "schedule_weekdays",
        "schedule_daily_start", "schedule_daily_end",
    }
    for field in schedule_fields & payload.model_fields_set:
        values[field] = getattr(payload, field)
    clear_schedule = values.pop("clear_schedule", False)
    if clear_schedule:
        values.update(
            schedule_start=None,
            schedule_end=None,
            schedule_weekdays=None,
            schedule_daily_start=None,
            schedule_daily_end=None,
        )
    if not values:
        return serialize(get_content_or_404(content_id))
    if "enabled" in values:
        values["enabled"] = int(values["enabled"])
    if "muted" in values:
        values["muted"] = int(values["muted"])
    if "play_to_end" in values:
        values["play_to_end"] = int(values["play_to_end"])
    if "schedule_weekdays" in values:
        weekdays = values["schedule_weekdays"]
        if weekdays is not None and any(day < 0 or day > 6 for day in weekdays):
            raise HTTPException(status_code=422, detail="Ungültiger Wochentag")
        values["schedule_weekdays"] = (
            json.dumps(sorted(set(weekdays))) if weekdays else None
        )
    for field in ("schedule_start", "schedule_end"):
        if values.get(field):
            try:
                values[field] = datetime.fromisoformat(values[field]).astimezone().isoformat()
            except ValueError as error:
                raise HTTPException(status_code=422, detail="Ungültiger Zeitpunkt") from error
    assignments = ", ".join(f"{key} = ?" for key in values)
    with connect() as connection:
        connection.execute(
            f"UPDATE content SET {assignments} WHERE id = ?",
            (*values.values(), content_id),
        )
    return serialize(get_content_or_404(content_id))


@app.delete("/api/content/{content_id}", status_code=204)
def delete_content(content_id: int, _: None = Depends(require_system_login)):
    row = get_content_or_404(content_id)
    text_config = json.loads(row["text_config"] or "{}") if row["kind"] == "text" else {}
    with connect() as connection:
        connection.execute("DELETE FROM content WHERE id = ?", (content_id,))
    if row["kind"] in {"image", "video", "pdf", "text"} and row["media_id"] is None:
        stored_name = Path(row["source"]).name
        (media_dir() / stored_name).unlink(missing_ok=True)
    if text_config.get("logo_source"):
        (media_dir() / Path(text_config["logo_source"]).name).unlink(missing_ok=True)


@app.get("/media/{filename}", include_in_schema=False)
def serve_media(filename: str):
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=404)
    path = media_dir() / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
