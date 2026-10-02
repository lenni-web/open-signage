"""Playlist content: uploads, free text, websites and livestreams."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..auth import require_system_login
from ..database import connect, media_dir
from ..image_processing import optimize_image
from ..media_probe import validate_video
from ..upload_security import save_upload
from ..video_processing import video_metadata, video_thumbnail
from .common import (active_playlist_id, content_rows, get_content_or_404, get_library_media_or_404,
                     serialize)

router = APIRouter()


class WebsiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    duration_seconds: int = Field(default=12, ge=1, le=86400)


class StreamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    duration_seconds: int = Field(default=3600, ge=1, le=86400)
    muted: bool = True


class LiveCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    duration_seconds: int = Field(default=300, ge=1, le=86400)
    muted: bool = False


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


@router.get("/api/content")
def list_content(_: None = Depends(require_system_login)):
    return content_rows()


@router.post("/api/content/upload", status_code=201)
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


@router.post("/api/content/text", status_code=201)
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


@router.post("/api/content/{content_id}/text")
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


@router.post("/api/content/website", status_code=201)
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


@router.post("/api/content/stream", status_code=201)
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


@router.post("/api/content/live", status_code=201)
def create_live(payload: LiveCreate, _: None = Depends(require_system_login)):
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
            VALUES (?, 'live', 'live', ?, ?, ?, ?)
            """,
            (payload.name, payload.duration_seconds, position, int(payload.muted), playlist_id),
        )
        content_id = cursor.lastrowid
    return serialize(get_content_or_404(content_id))


@router.patch("/api/content/{content_id}")
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


@router.delete("/api/content/{content_id}", status_code=204)
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
