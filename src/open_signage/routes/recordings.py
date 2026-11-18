"""Aufnahmen der Live-Übertragungen verwalten und herunterladen."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import live, recordings
from ..auth import device_mode, require_system_login

router = APIRouter()


class RecordingSettings(BaseModel):
    enabled: bool


def _require_ingest() -> None:
    if device_mode() == "display":
        raise HTTPException(status_code=409, detail="Aufnahmen entstehen auf dem Controller")


def _recording(name: str):
    try:
        return recordings.recording_path(name)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Aufnahme nicht gefunden") from error


@router.get("/api/recordings")
def list_recordings(_: None = Depends(require_system_login)):
    if device_mode() == "display":
        return {"available": False, "enabled": False, "keep": recordings.KEEP, "recordings": []}
    recordings.cleanup()
    return {"available": True, "enabled": live.recording_enabled(), "keep": recordings.KEEP,
            "recordings": recordings.list_recordings()}


@router.put("/api/recordings/settings")
def update_recording_settings(payload: RecordingSettings, _: None = Depends(require_system_login)):
    _require_ingest()
    live.set_recording_enabled(payload.enabled)
    return {"enabled": live.recording_enabled()}


@router.get("/api/recordings/{name}/download")
def download_recording(name: str, audio: str = Query(default="original", pattern="^(original|aac)$"),
                       _: None = Depends(require_system_login)):
    _require_ingest()
    path = _recording(name)
    if audio == "aac":
        path = recordings.converted_path(name)
        if not path.is_file():
            raise HTTPException(status_code=409, detail="Die Aufnahme wurde noch nicht umgewandelt")
    return FileResponse(path, media_type="video/mp4", filename=recordings.download_name(name, audio == "aac"),
                        headers={"Cache-Control": "private, no-store"})


@router.post("/api/recordings/{name}/convert", status_code=202)
def convert_recording(name: str, _: None = Depends(require_system_login)):
    _require_ingest()
    _recording(name)
    try:
        return recordings.start_conversion(name)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/api/recordings/{name}", status_code=204)
def delete_recording(name: str, _: None = Depends(require_system_login)):
    _require_ingest()
    _recording(name)
    try:
        recordings.delete_recording(name)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
