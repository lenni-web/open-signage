from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

DEFAULT_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
MIN_FREE_BYTES = 512 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024

SUFFIXES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "video/mp4": ".mp4", "video/webm": ".webm",
    "application/pdf": ".pdf",
}
KINDS = {mime: mime.split("/", 1)[0] for mime in SUFFIXES}
KINDS["application/pdf"] = "pdf"


def max_upload_bytes() -> int:
    try:
        return max(CHUNK_SIZE, int(os.environ.get("OPEN_SIGNAGE_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)))
    except ValueError:
        return DEFAULT_MAX_UPLOAD_BYTES


def detect_media_type(path: Path) -> str | None:
    with path.open("rb") as source:
        header = source.read(32)
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] in {b"GIF8"}:
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    return None


def ensure_free_space(directory: Path, incoming_bytes: int = 0) -> None:
    usage = shutil.disk_usage(directory)
    reserve = max(MIN_FREE_BYTES, int(usage.total * 0.05))
    if usage.free - incoming_bytes < reserve:
        raise HTTPException(
            status_code=507,
            detail="Zu wenig freier Speicher. Mindestens 512 MB bzw. 5 % bleiben reserviert.",
        )


def save_upload(file: UploadFile, directory: Path, allowed_kinds: set[str]) -> tuple[Path, str, int]:
    ensure_free_space(directory)
    temporary = directory / f".{uuid.uuid4().hex}.upload"
    size = 0
    try:
        with temporary.open("xb") as output:
            while chunk := file.file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_upload_bytes():
                    raise HTTPException(status_code=413, detail="Datei ist zu groß")
                ensure_free_space(directory, len(chunk))
                output.write(chunk)
        media_type = detect_media_type(temporary)
        kind = KINDS.get(media_type or "")
        if kind not in allowed_kinds:
            raise HTTPException(status_code=415, detail="Dateityp oder Dateiinhalt wird nicht unterstützt.")
        destination = directory / f"{uuid.uuid4().hex}{SUFFIXES[media_type]}"
        temporary.replace(destination)
        return destination, kind, size
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()
