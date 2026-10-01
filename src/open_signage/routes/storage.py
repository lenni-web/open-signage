"""Storage audit, cleanup and backups."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import require_system_login
from ..backup import backup_dir, create_backup, list_backups, restore_backup, validate_backup
from ..database import connect, data_dir, media_dir
from ..media_files import file_sha256, referenced_media_files
from .common import local_media_exists

router = APIRouter()


class BackupCreate(BaseModel):
    include_media: bool = False


@router.get("/api/system/storage")
def storage_status(_: None = Depends(require_system_login)):
    with connect() as connection:
        rows = connection.execute("SELECT * FROM media_library").fetchall()
        used = {row[0] for row in connection.execute("SELECT DISTINCT media_id FROM content WHERE media_id IS NOT NULL")}
        known = referenced_media_files(connection)
    files = [path for path in media_dir().iterdir() if path.is_file()]
    missing = [row["id"] for row in rows if not local_media_exists(row["source"])]
    orphan = [path for path in files if path.name not in known]
    hashes: dict[str, list[int]] = {}
    for row in rows:
        path = media_dir() / Path(row["source"]).name
        if path.is_file():
            digest = file_sha256(path)
            hashes.setdefault(digest, []).append(row["id"])
    duplicates = [ids for ids in hashes.values() if len(ids) > 1]
    return {"media_count": len(rows), "unused_media_count": sum(row["id"] not in used for row in rows),
            "media_bytes": sum(path.stat().st_size for path in files), "file_count": len(files),
            "missing_media_ids": missing, "orphan_file_count": len(orphan),
            "orphan_bytes": sum(path.stat().st_size for path in orphan), "duplicate_groups": duplicates}


@router.get("/api/system/backups")
def get_backups(_: None = Depends(require_system_login)):
    return list_backups()


@router.post("/api/system/backups", status_code=201)
def start_backup(payload: BackupCreate, _: None = Depends(require_system_login)):
    try:
        return create_backup(include_media=payload.include_media)
    except (OSError, RuntimeError) as error:
        raise HTTPException(status_code=500, detail=f"Backup fehlgeschlagen: {error}") from error


@router.get("/api/system/backups/{filename}")
def download_backup(filename: str, _: None = Depends(require_system_login)):
    if Path(filename).name != filename:
        raise HTTPException(status_code=404)
    path = backup_dir() / filename
    if not path.is_file(): raise HTTPException(status_code=404, detail="Backup nicht gefunden")
    return FileResponse(path, filename=filename, media_type="application/zip")


@router.post("/api/system/backups/restore")
def restore_uploaded_backup(
    file: Annotated[UploadFile, File()], _: None = Depends(require_system_login)
):
    temporary = data_dir() / ".restore-upload.zip"
    try:
        size = 0
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > 5 * 1024 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Backup ist zu groß")
                output.write(chunk)
        validate_backup(temporary)
        restore_backup(temporary)
    except (ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise HTTPException(status_code=415, detail=f"Ungültiges Backup: {error}") from error
    finally:
        file.file.close(); temporary.unlink(missing_ok=True)
    return {"restored": True, "message": "Backup wiederhergestellt. Anwendung bitte neu starten."}


@router.post("/api/system/storage/cleanup")
def cleanup_storage(_: None = Depends(require_system_login)):
    removed_media = 0
    removed_files = 0
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM media_library WHERE id NOT IN (SELECT DISTINCT media_id FROM content WHERE media_id IS NOT NULL)"
        ).fetchall()
        for row in rows:
            for source in {row["source"], row["original_source"], row["thumbnail_source"]}:
                if source:
                    path = media_dir() / Path(source).name
                    if path.exists(): path.unlink(); removed_files += 1
            connection.execute("DELETE FROM media_library WHERE id = ?", (row["id"],))
            removed_media += 1
    return {"removed_media": removed_media, "removed_files": removed_files}


@router.post("/api/system/storage/orphans/cleanup")
def cleanup_orphan_files(_: None = Depends(require_system_login)):
    with connect() as connection:
        known = referenced_media_files(connection)
    removed = 0; removed_bytes = 0
    for path in media_dir().iterdir():
        if path.is_file() and path.name not in known:
            removed_bytes += path.stat().st_size; path.unlink(); removed += 1
    return {"removed_files": removed, "removed_bytes": removed_bytes}
