from __future__ import annotations

import mimetypes
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import connect, initialize, media_dir
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
    duration_seconds: int = Field(default=30, ge=1, le=86400)


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


def serialize(row) -> dict:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["muted"] = bool(item["muted"])
    return item


def get_content_or_404(content_id: int):
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM content WHERE id = ?", (content_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Inhalt nicht gefunden")
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
def system_info():
    return collect_system_info()


@app.get("/api/system/update")
def get_system_update():
    return update_status()


@app.post("/api/system/update", status_code=202)
def start_system_update():
    try:
        return request_update()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/content")
def list_content(enabled_only: bool = False):
    query = "SELECT * FROM content"
    params: tuple = ()
    if enabled_only:
        query += " WHERE enabled = ?"
        params = (1,)
    query += " ORDER BY position, id"
    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [serialize(row) for row in rows]


@app.post("/api/content/upload", status_code=201)
def upload_content(
    file: Annotated[UploadFile, File()],
    duration_seconds: Annotated[int, Form(ge=1, le=86400)] = 10,
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


@app.post("/api/content/website", status_code=201)
def create_website(payload: WebsiteCreate):
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
def create_stream(payload: StreamCreate):
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
def update_content(content_id: int, payload: ContentUpdate):
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
def delete_content(content_id: int):
    row = get_content_or_404(content_id)
    with connect() as connection:
        connection.execute("DELETE FROM content WHERE id = ?", (content_id,))
    if row["kind"] in {"image", "video", "pdf"}:
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
    return FileResponse(path)
