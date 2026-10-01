"""Shared helpers for content, playlists and media used by several routers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

from ..database import connect, media_dir

PACKAGE_DIR = Path(__file__).parents[1]
STATIC_DIR = PACKAGE_DIR / "static"


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


def serialize_playlist(row) -> dict:
    item = dict(row)
    item["active"] = bool(item["active"])
    item["schedule_enabled"] = bool(item["schedule_enabled"])
    item["schedule_weekdays"] = json.loads(item["schedule_weekdays"] or "[]")
    item["effective"] = item["id"] == active_playlist_id()
    return item


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
