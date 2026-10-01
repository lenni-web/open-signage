"""Controller endpoints that registered displays synchronize from."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..auth import device_mode
from ..database import media_dir
from ..sync import authenticate_device, register_device, snapshot as sync_snapshot

router = APIRouter()


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
def get_sync_snapshot(_: None = Depends(require_sync_device)):
    if device_mode() != "controller": raise HTTPException(status_code=409, detail="Gerät ist kein Controller")
    return sync_snapshot()


@router.get("/api/sync/media/{filename}")
def get_sync_media(filename: str, _: None = Depends(require_sync_device)):
    if Path(filename).name != filename: raise HTTPException(status_code=404)
    path = media_dir() / filename
    if not path.is_file(): raise HTTPException(status_code=404)
    return FileResponse(path)
