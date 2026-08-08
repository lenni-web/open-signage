from __future__ import annotations

import mimetypes
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import connect, initialize, media_dir
from .auth import change_password, create_session, destroy_session, require_system_login, screen_name, set_setting, verify_password
from .application_update import request_update as request_application_update
from .application_update import update_status as application_update_status
from .media_probe import inspect_video
from .system_info import collect_system_info
from .system_update import request_update, update_status
from .version import __version__

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"
ALLOWED_MEDIA_TYPES = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/gif": "image",
    "video/mp4": "video",
    "video/webm": "video",
    "application/pdf": "pdf",
}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="Open Signage", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class WebsiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    duration_seconds: int = Field(default=12, ge=1, le=86400)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


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


class LibraryPlaylistCreate(BaseModel):
    duration_seconds: int = Field(default=10, ge=1, le=86400)


def serialize(row) -> dict:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["muted"] = bool(item["muted"])
    item["text_config"] = json.loads(item["text_config"]) if item.get("text_config") else None
    return item


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


@app.get("/", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/player", include_in_schema=False)
def player_page():
    return FileResponse(STATIC_DIR / "player.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/system/info")
def system_info(_: None = Depends(require_system_login)):
    return collect_system_info()


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


@app.get("/api/system/session")
def system_session(_: None = Depends(require_system_login)):
    return {"authenticated": True, "screen_name": screen_name()}


@app.post("/api/system/login")
def system_login(payload: LoginRequest, response: Response):
    if not verify_password(payload.password):
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    create_session(response)
    return {"authenticated": True, "screen_name": screen_name()}


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
    query = "SELECT * FROM content"
    params: tuple = ()
    if enabled_only:
        query += " WHERE enabled = ?"
        params = (1,)
    query += " ORDER BY position, id"
    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [serialize(row) for row in rows]


@app.get("/api/player/content")
def player_content():
    return content_rows(enabled_only=True)


@app.get("/api/content")
def list_content(_: None = Depends(require_system_login)):
    return content_rows()


@app.post("/api/content/upload", status_code=201)
def upload_content(
    file: Annotated[UploadFile, File()],
    duration_seconds: Annotated[int, Form(ge=1, le=86400)] = 10,
    _: None = Depends(require_system_login),
):
    media_type = file.content_type
    if media_type not in ALLOWED_MEDIA_TYPES:
        media_type = mimetypes.guess_type(file.filename or "")[0]
    kind = ALLOWED_MEDIA_TYPES.get(media_type or "")
    if kind is None:
        raise HTTPException(
            status_code=415,
            detail="Erlaubt sind JPG, PNG, WebP, GIF, MP4, WebM und PDF",
        )

    suffix = Path(file.filename or "").suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = media_dir() / stored_name
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Datei ist zu groß")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()

    if kind == "pdf":
        with destination.open("rb") as uploaded_pdf:
            if uploaded_pdf.read(5) != b"%PDF-":
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=415,
                    detail="Die Datei ist kein gültiges PDF-Dokument.",
                )

    compatibility = inspect_video(destination) if kind == "video" else None

    with connect() as connection:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content"
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(name, kind, source, duration_seconds, position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                Path(file.filename or stored_name).name,
                kind,
                f"/media/{stored_name}",
                duration_seconds,
                position,
            ),
        )
        content_id = cursor.lastrowid
    response = serialize(get_content_or_404(content_id))
    if compatibility is not None:
        response["compatibility"] = compatibility
    return response


def save_text_background(file: UploadFile) -> str:
    media_type = file.content_type
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        media_type = mimetypes.guess_type(file.filename or "")[0]
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(
            status_code=415,
            detail="Als Freitext-Hintergrund sind JPG, PNG und WebP erlaubt.",
        )
    suffix = Path(file.filename or "").suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = media_dir() / stored_name
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Datei ist zu groß")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()
    return f"/media/{stored_name}"


@app.get("/api/media-library")
def list_media_library(_: None = Depends(require_system_login)):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM media_library ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/media-library", status_code=201)
def upload_library_media(
    file: Annotated[UploadFile, File()],
    _: None = Depends(require_system_login),
):
    media_type = file.content_type
    if media_type not in ALLOWED_MEDIA_TYPES:
        media_type = mimetypes.guess_type(file.filename or "")[0]
    kind = ALLOWED_MEDIA_TYPES.get(media_type or "")
    if kind not in {"image", "video"}:
        raise HTTPException(
            status_code=415,
            detail="Für die Mediathek sind JPG, PNG, WebP, GIF, MP4 und WebM erlaubt.",
        )
    suffix = Path(file.filename or "").suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = media_dir() / stored_name
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Datei ist zu groß")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()
    compatibility = inspect_video(destination) if kind == "video" else None
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO media_library(name, kind, source, size_bytes) VALUES (?, ?, ?, ?)",
            (Path(file.filename or stored_name).name, kind, f"/media/{stored_name}", size),
        )
        media_id = cursor.lastrowid
    response = dict(get_library_media_or_404(media_id))
    if compatibility is not None:
        response["compatibility"] = compatibility
    return response


@app.post("/api/media-library/{media_id}/playlist", status_code=201)
def add_library_media_to_playlist(
    media_id: int,
    payload: LibraryPlaylistCreate,
    _: None = Depends(require_system_login),
):
    media = get_library_media_or_404(media_id)
    with connect() as connection:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content"
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(name, kind, source, duration_seconds, position, media_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (media["name"], media["kind"], media["source"], payload.duration_seconds, position, media_id),
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
    (media_dir() / Path(media["source"]).name).unlink(missing_ok=True)


def text_configuration(
    headline: str,
    subheadline: str,
    body: str,
    shadow_box: bool,
    shadow_intensity: str,
) -> str:
    if not any(value.strip() for value in (headline, subheadline, body)):
        raise HTTPException(status_code=422, detail="Mindestens ein Textfeld muss ausgefüllt sein")
    if shadow_intensity not in {"light", "medium", "dark"}:
        raise HTTPException(status_code=422, detail="Ungültige Schattenbox-Intensität")
    return json.dumps(
        {
            "headline": headline.strip(),
            "subheadline": subheadline.strip(),
            "body": body.strip(),
            "shadow_box": shadow_box,
            "shadow_intensity": shadow_intensity,
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
    duration_seconds: Annotated[int, Form(ge=1, le=86400)] = 12,
    background: Annotated[UploadFile | None, File()] = None,
    library_media_id: Annotated[int | None, Form()] = None,
    _: None = Depends(require_system_login),
):
    config = text_configuration(headline, subheadline, body, shadow_box, shadow_intensity)
    library_media = get_library_media_or_404(library_media_id) if library_media_id else None
    if library_media and library_media["kind"] != "image":
        raise HTTPException(status_code=422, detail="Als Freitext-Hintergrund ist nur ein Bild möglich")
    if background and background.filename:
        source = save_text_background(background)
        library_media_id = None
    elif library_media:
        source = library_media["source"]
    else:
        raise HTTPException(status_code=422, detail="Bitte ein Hintergrundbild auswählen")
    try:
        with connect() as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM content"
            ).fetchone()[0]
            cursor = connection.execute(
                """
                INSERT INTO content(name, kind, source, duration_seconds, position, text_config, media_id)
                VALUES (?, 'text', ?, ?, ?, ?, ?)
                """,
                (name.strip(), source, duration_seconds, position, config, library_media_id),
            )
            content_id = cursor.lastrowid
    except Exception:
        if not library_media_id:
            (media_dir() / Path(source).name).unlink(missing_ok=True)
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
    duration_seconds: Annotated[int, Form(ge=1, le=86400)] = 12,
    background: Annotated[UploadFile | None, File()] = None,
    library_media_id: Annotated[int | None, Form()] = None,
    _: None = Depends(require_system_login),
):
    row = get_content_or_404(content_id)
    if row["kind"] != "text":
        raise HTTPException(status_code=422, detail="Dieser Inhalt ist kein Freitext")
    config = text_configuration(headline, subheadline, body, shadow_box, shadow_intensity)
    source = row["source"]
    selected_media = get_library_media_or_404(library_media_id) if library_media_id else None
    if selected_media and selected_media["kind"] != "image":
        raise HTTPException(status_code=422, detail="Als Freitext-Hintergrund ist nur ein Bild möglich")
    new_source = save_text_background(background) if background and background.filename else None
    if new_source:
        source = new_source
        library_media_id = None
    elif selected_media:
        source = selected_media["source"]
    else:
        library_media_id = row["media_id"]
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
        raise
    if source != row["source"] and row["media_id"] is None:
        (media_dir() / Path(row["source"]).name).unlink(missing_ok=True)
    return serialize(get_content_or_404(content_id))


@app.post("/api/content/website", status_code=201)
def create_website(payload: WebsiteCreate, _: None = Depends(require_system_login)):
    parsed = urlparse(payload.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Ungültige HTTP(S)-Adresse")
    with connect() as connection:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content"
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(name, kind, source, duration_seconds, position)
            VALUES (?, 'website', ?, ?, ?)
            """,
            (payload.name, payload.url, payload.duration_seconds, position),
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
    with connect() as connection:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM content"
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO content(
                name, kind, source, duration_seconds, position, muted
            )
            VALUES (?, 'stream', ?, ?, ?, ?)
            """,
            (
                payload.name,
                stream_url,
                payload.duration_seconds,
                position,
                int(payload.muted),
            ),
        )
        content_id = cursor.lastrowid
    return serialize(get_content_or_404(content_id))


@app.patch("/api/content/{content_id}")
def update_content(content_id: int, payload: ContentUpdate, _: None = Depends(require_system_login)):
    get_content_or_404(content_id)
    values = payload.model_dump(exclude_none=True)
    if not values:
        return serialize(get_content_or_404(content_id))
    if "enabled" in values:
        values["enabled"] = int(values["enabled"])
    if "muted" in values:
        values["muted"] = int(values["muted"])
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
    with connect() as connection:
        connection.execute("DELETE FROM content WHERE id = ?", (content_id,))
    if row["kind"] in {"image", "video", "pdf", "text"} and row["media_id"] is None:
        stored_name = Path(row["source"]).name
        (media_dir() / stored_name).unlink(missing_ok=True)


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
