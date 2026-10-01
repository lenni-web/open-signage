"""HTML pages, health check and media file delivery."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from ..database import media_dir
from ..version import __version__
from .common import STATIC_DIR

router = APIRouter()


@router.get("/", include_in_schema=False)
def admin_page():
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("@@VERSION@@", __version__), headers={"Cache-Control": "no-store"})


@router.get("/player", include_in_schema=False)
def player_page():
    html = (STATIC_DIR / "player.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("@@VERSION@@", __version__), headers={"Cache-Control": "no-store"})


@router.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/media/{filename}", include_in_schema=False)
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
