"""Controller endpoints that registered displays synchronize from."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import live
from ..announcement import local_announcement
from ..auth import device_mode
from ..database import media_dir
from ..sync import (MAX_SCREENSHOT_BYTES, authenticate_device, device_for_token, register_device,
                    screenshots_wanted, snapshot as sync_snapshot, store_device_screenshot, store_device_status,
                    take_device_command)

router = APIRouter()

MAX_STATUS_BYTES = 32 * 1024


class SyncRegistration(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    pairing_token: str = Field(min_length=1, max_length=200)


def require_sync_device(request: Request) -> None:
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    if not authenticate_device(token): raise HTTPException(status_code=401, detail="Ungültiger Geräte-Token")


@router.post("/api/sync/register")
def sync_register(payload: SyncRegistration):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    try:
        token = register_device(payload.device_id, payload.name, payload.pairing_token)
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return {"device_token": token}


@router.get("/api/sync/snapshot")
def get_sync_snapshot(request: Request, _: None = Depends(require_sync_device)):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    return sync_snapshot(_device_id(request))


@router.get("/api/sync/live")
def get_sync_live(_: None = Depends(require_sync_device)):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    state = live.local_state()
    return {**{key: state[key] for key in ("server_running", "available", "takeover", "sound")},
            "announcement": local_announcement()}


def _device_id(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    device_id = device_for_token(authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else "")
    if not device_id: raise HTTPException(status_code=401, detail="Ungültiger Geräte-Token")
    return device_id


@router.get("/api/sync/commands")
def get_device_command(request: Request):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    return {"command": take_device_command(_device_id(request)), "screenshot": screenshots_wanted()}


@router.post("/api/sync/screenshot", status_code=204)
async def receive_device_screenshot(request: Request):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    device_id = _device_id(request)
    image = await request.body()
    if len(image) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status_code=413, detail="Bildschirmfoto ist zu groß")
    if not image.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="Bildschirmfoto muss ein JPEG sein")
    store_device_screenshot(device_id, image)


@router.post("/api/sync/status", status_code=204)
def receive_device_status(payload: dict, request: Request):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    device_id = _device_id(request)
    if len(json.dumps(payload)) > MAX_STATUS_BYTES:
        raise HTTPException(status_code=413, detail="Statusmeldung ist zu groß")
    # Die Adresse, unter der das Display den Controller erreicht – funktioniert auch mit älteren Displays.
    host = request.client.host if request.client else None
    payload["reported_address"] = host.removeprefix("::ffff:") if host else None
    store_device_status(device_id, payload)


@router.get("/api/sync/media/{filename}")
def get_sync_media(filename: str, _: None = Depends(require_sync_device)):
    if Path(filename).name != filename: raise HTTPException(status_code=404)
    path = media_dir() / filename
    if not path.is_file(): raise HTTPException(status_code=404)
    return FileResponse(path)
