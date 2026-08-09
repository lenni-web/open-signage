from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from .database import connect, media_dir
from .upload_security import ensure_free_space
from .video_processing import transcode_video

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="open-signage-video")


def _set_job(job_id: str, status: str, message: str = "") -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE conversion_jobs SET status = ?, message = ?, updated_at = ? WHERE id = ?",
            (status, message[:500], datetime.now(UTC).isoformat(), job_id),
        )


def _convert(job_id: str, media_id: int, source_path: Path, original_source: str) -> None:
    _set_job(job_id, "running")
    try:
        # Reserve room for an output approximately as large as the input.
        ensure_free_space(media_dir(), source_path.stat().st_size)
        source, metadata, thumbnail = transcode_video(source_path, media_dir())
        ensure_free_space(media_dir())
        with connect() as connection:
            media = connection.execute(
                "SELECT source, thumbnail_source FROM media_library WHERE id = ?", (media_id,)
            ).fetchone()
            if not media:
                raise RuntimeError("Medium wurde während der Konvertierung gelöscht")
            connection.execute(
                """UPDATE media_library SET source = ?, original_source = ?, thumbnail_source = ?,
                   width = ?, height = ?, metadata_json = ? WHERE id = ?""",
                (source, original_source, thumbnail, metadata.get("width"), metadata.get("height"),
                 json.dumps(metadata), media_id),
            )
            connection.execute("UPDATE content SET source = ? WHERE media_id = ?", (source, media_id))
        for old in (media["thumbnail_source"], media["source"]):
            if old and old not in {original_source, source}:
                (media_dir() / Path(old).name).unlink(missing_ok=True)
        _set_job(job_id, "completed", "Video wurde optimal konvertiert.")
    except Exception as error:
        _set_job(job_id, "failed", f"Videokonvertierung fehlgeschlagen: {error}")


def queue_conversion(media_id: int, source_path: Path, original_source: str) -> str:
    with connect() as connection:
        active = connection.execute(
            "SELECT id FROM conversion_jobs WHERE media_id = ? AND status IN ('queued', 'running')",
            (media_id,),
        ).fetchone()
        if active:
            return active["id"]
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        connection.execute(
            "INSERT INTO conversion_jobs(id, media_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?)", (job_id, media_id, now, now),
        )
    _executor.submit(_convert, job_id, media_id, source_path, original_source)
    return job_id


def conversion_status(job_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM conversion_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None
