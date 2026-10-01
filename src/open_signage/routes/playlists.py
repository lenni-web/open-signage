"""Playlist management and scheduling."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_system_login
from ..database import connect, media_dir
from .common import serialize_playlist

router = APIRouter()


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PlaylistScheduleUpdate(BaseModel):
    schedule_enabled: bool = False
    schedule_start: str | None = Field(default=None, max_length=32)
    schedule_end: str | None = Field(default=None, max_length=32)
    schedule_weekdays: list[int] = Field(default_factory=list)
    schedule_daily_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_daily_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/api/playlists")
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


@router.patch("/api/playlists/{playlist_id}/schedule")
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


@router.post("/api/playlists", status_code=201)
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


@router.post("/api/playlists/{playlist_id}/activate")
def activate_playlist(playlist_id: int, _: None = Depends(require_system_login)):
    with connect() as connection:
        exists = connection.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Playlist nicht gefunden")
        connection.execute("UPDATE playlists SET active = 0")
        connection.execute("UPDATE playlists SET active = 1 WHERE id = ?", (playlist_id,))
    return {"active_playlist_id": playlist_id}


@router.delete("/api/playlists/{playlist_id}", status_code=204)
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
