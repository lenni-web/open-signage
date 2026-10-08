"""Device information, updates, device role and display control."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import live
from ..application_update import (request_update as request_application_update, update_status as
                                  application_update_status)
from ..auth import (device_mode, get_setting, lan_player_access_enabled, password_change_required,
                    require_system_login, set_setting, verify_password)
from ..backup import list_backups
from ..database import connect, data_dir
from ..display_control import (display_config, display_status, request_display_action,
                               save_display_config, schedule_analysis)
from ..sync import pairing_token, safe_sync_from_controller
from ..system_info import collect_system_info
from ..system_update import request_update, update_status
from ..version import __version__

router = APIRouter()


class DeviceSettings(BaseModel):
    role: str = Field(pattern=r"^(standalone|controller|display)$")
    controller_url: str = Field(default="", max_length=2048)
    pairing_code: str = Field(default="", max_length=200)
    current_password: str = Field(default="", max_length=200)


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
    transition_ms: int = Field(default=4000, ge=1000, le=6000)
    schedule_enabled: bool = False
    schedule_entries: list[DisplayScheduleEntry] = Field(default_factory=list, max_length=100)


class DisplayAction(BaseModel):
    action: str = Field(pattern=r"^(on|off|status|resolution)$")


class PlayerAccessSettings(BaseModel):
    lan_access: bool


@router.get("/api/system/monitoring")
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


@router.get("/api/system/info")
def system_info(_: None = Depends(require_system_login)):
    return collect_system_info()


@router.get("/api/system/security-status")
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


@router.get("/api/system/update")
def get_system_update(_: None = Depends(require_system_login)):
    return update_status()


@router.post("/api/system/update", status_code=202)
def start_system_update(_: None = Depends(require_system_login)):
    try:
        return request_update()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/system/application-update")
def get_application_update(_: None = Depends(require_system_login)):
    return application_update_status()


@router.post("/api/system/application-update", status_code=202)
def start_application_update(_: None = Depends(require_system_login)):
    try:
        return request_application_update()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/system/device")
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
    last_warning = get_setting("sync_last_warning", "") if role == "display" else ""
    status = "bereit" if role != "display" else (
        f"zuletzt {last_success}" if last_success else f"offline: {last_error}" if last_error else "noch nicht verbunden")
    if last_warning: status += f" · {last_warning}"
    return {"device_id": device_id, "role": role, "controller_url": controller_url,
            "pairing_code": pairing_token() if role == "controller" else "",
            "registered_devices": devices, "last_success": last_success, "last_error": last_error,
            "last_warning": last_warning, "sync_status": status}


@router.patch("/api/system/device")
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
    live.write_config()
    return get_device_settings(_)


@router.post("/api/system/device/sync")
def sync_device_now(_: None = Depends(require_system_login)):
    if device_mode() != "display":
        raise HTTPException(status_code=409, detail="Nur ein Display kann vom Controller synchronisieren")
    result = safe_sync_from_controller()
    if result["status"] == "offline": raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.post("/api/system/action", status_code=202)
def request_system_action(payload: SystemAction, _: None = Depends(require_system_login)):
    (data_dir() / "system-action-request").write_text(payload.action, encoding="utf-8")
    return {"queued": True, "action": payload.action}


@router.get("/api/system/display-control")
def get_display_control(_: None = Depends(require_system_login)):
    config = display_config()
    return {"config": config, "status": display_status(), "schedule": schedule_analysis(config)}


@router.patch("/api/system/display-control")
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


@router.post("/api/system/display-control/action", status_code=202)
def start_display_action(payload: DisplayAction, _: None = Depends(require_system_login)):
    request_display_action(payload.action)
    return {"queued": True, "action": payload.action}


@router.get("/api/system/player-access")
def get_player_access(_: None = Depends(require_system_login)):
    return {"lan_access": lan_player_access_enabled()}


@router.patch("/api/system/player-access")
def update_player_access(payload: PlayerAccessSettings, _: None = Depends(require_system_login)):
    set_setting("player_lan_access", "1" if payload.lan_access else "0")
    return {"lan_access": lan_player_access_enabled()}
