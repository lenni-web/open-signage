"""Media library management, image editing and video conversion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..auth import require_system_login
from ..conversion_jobs import conversion_status, queue_conversion
from ..database import connect, media_dir
from ..image_processing import edit_image, optimize_image
from ..media_probe import validate_video
from ..upload_security import ensure_free_space, save_upload
from ..video_processing import video_metadata, video_thumbnail
from .common import (active_playlist_id, get_content_or_404, get_library_media_or_404, serialize,
                     serialize_library_media)

router = APIRouter()


class LibraryPlaylistCreate(BaseModel):
    duration_seconds: int = Field(default=10, ge=1, le=86400)
    muted: bool = True
    play_to_end: bool = False


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


@router.get("/api/media-library")
def list_media_library(_: None = Depends(require_system_login)):
    with connect() as connection:
        rows = connection.execute(
            """SELECT media_library.*, COUNT(content.id) AS usage_count
               FROM media_library LEFT JOIN content ON content.media_id = media_library.id
               GROUP BY media_library.id ORDER BY created_at DESC, media_library.id DESC"""
        ).fetchall()
    return [serialize_library_media(row) for row in rows]


@router.post("/api/media-library", status_code=201)
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


@router.patch("/api/media-library/{media_id}")
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


@router.post("/api/media-library/{media_id}/replace")
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


@router.post("/api/media-library/bulk-playlist", status_code=201)
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


@router.post("/api/media-library/{media_id}/transcode", status_code=202)
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


@router.get("/api/conversions/{job_id}")
def get_conversion(job_id: str, _: None = Depends(require_system_login)):
    job = conversion_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Konvertierungsauftrag nicht gefunden")
    if job["status"] == "completed":
        job["media"] = serialize_library_media(get_library_media_or_404(job["media_id"]))
    return job


@router.post("/api/media-library/{media_id}/edit-image")
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


@router.post("/api/media-library/{media_id}/playlist", status_code=201)
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


@router.delete("/api/media-library/{media_id}", status_code=204)
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
