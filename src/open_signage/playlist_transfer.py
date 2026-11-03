"""Export and import of a single playlist with its media as a ZIP archive."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .database import connect, data_dir, media_dir
from .media_files import file_sha256, media_filename
from .upload_security import detect_media_type, ensure_free_space
from .version import __version__

FORMAT = "open-signage-playlist"
FORMAT_VERSION = 1
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024 * 1024
CONTENT_KINDS = {"image", "video", "pdf", "website", "stream", "text", "live"}
PLAYLIST_FIELDS = ("schedule_enabled", "schedule_start", "schedule_end", "schedule_weekdays",
                   "schedule_daily_start", "schedule_daily_end")
LIBRARY_FIELDS = ("name", "kind", "source", "size_bytes", "original_source", "thumbnail_source",
                  "width", "height", "category", "metadata_json")
CONTENT_FIELDS = ("name", "kind", "source", "duration_seconds", "position", "enabled", "muted",
                  "play_to_end", "text_config", "schedule_start", "schedule_end", "schedule_weekdays",
                  "schedule_daily_start", "schedule_daily_end")
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".pdf"}


class TransferError(ValueError):
    """The archive is not a usable playlist export."""


def _logo(text_config: str | None) -> str | None:
    try:
        return json.loads(text_config or "{}").get("logo_source")
    except (ValueError, AttributeError):
        return None


def export_playlist(playlist_id: int) -> tuple[Path, str]:
    """Write the playlist to a temporary ZIP; returns its path and the playlist name."""
    with connect() as connection:
        playlist = connection.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not playlist:
            raise LookupError(playlist_id)
        contents = connection.execute(
            "SELECT * FROM content WHERE playlist_id = ? ORDER BY position, id", (playlist_id,)
        ).fetchall()
        media_ids = sorted({row["media_id"] for row in contents if row["media_id"] is not None})
        library = [connection.execute("SELECT * FROM media_library WHERE id = ?", (media_id,)).fetchone()
                   for media_id in media_ids]
    files = set()
    for row in library:
        files.update(media_filename(row[key]) for key in ("source", "original_source", "thumbnail_source"))
    for row in contents:
        files.update((media_filename(row["source"]), media_filename(_logo(row["text_config"]))))
    files.discard(None)
    missing = sorted(name for name in files if not (media_dir() / name).is_file())
    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION, "app_version": __version__,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "playlist": {"name": playlist["name"], **{key: playlist[key] for key in PLAYLIST_FIELDS}},
        "media_library": [{"ref": row["id"], **{key: row[key] for key in LIBRARY_FIELDS}} for row in library],
        "content": [{"media_ref": row["media_id"], **{key: row[key] for key in CONTENT_FIELDS}}
                    for row in contents],
        "files": sorted(files - set(missing)),
        "missing_files": missing,
    }
    handle, name = tempfile.mkstemp(prefix=".playlist-export-", suffix=".zip", dir=data_dir())
    os.close(handle)
    target = Path(name)
    try:
        # Medien sind bereits komprimiert; Speichern ohne Kompression schont den Pi.
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2),
                             compress_type=zipfile.ZIP_DEFLATED)
            for filename in manifest["files"]:
                archive.write(media_dir() / filename, f"media/{filename}")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, playlist["name"]


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, ValueError) as error:
        raise TransferError("Die Datei ist kein Playlist-Export von Open Signage.") from error
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise TransferError("Die Datei ist kein Playlist-Export von Open Signage.")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise TransferError("Dieses Exportformat wird von dieser Version nicht unterstützt.")
    if not isinstance(manifest.get("playlist"), dict) or not str(manifest["playlist"].get("name", "")).strip():
        raise TransferError("Der Export enthält keine gültige Playlist.")
    for key in ("media_library", "content", "files"):
        if not isinstance(manifest.get(key), list):
            raise TransferError("Der Export ist unvollständig.")
    return manifest


def _unique_name(connection: sqlite3.Connection, name: str) -> str:
    name = name.strip()[:100]
    candidate, number = name, 1
    while connection.execute("SELECT 1 FROM playlists WHERE name = ?", (candidate,)).fetchone():
        number += 1
        suffix = " (Import)" if number == 2 else f" (Import {number - 1})"
        candidate = name[: 100 - len(suffix)] + suffix
    return candidate


def _extract_media(archive: zipfile.ZipFile, filenames: list[str], workdir: Path) -> tuple[dict[str, str], list[Path]]:
    """Copy the archive's media into the media directory.

    Returns a filename map (old -> new) and the files that were newly created. Identical files already
    present are reused; a different file with the same name gets a new name.
    """
    renamed: dict[str, str] = {}
    created: list[Path] = []
    for filename in filenames:
        member = f"media/{filename}"
        if Path(filename).name != filename or Path(filename).suffix.lower() not in MEDIA_SUFFIXES:
            raise TransferError(f"Unzulässiger Dateiname im Export: {filename}")
        try:
            info = archive.getinfo(member)
        except KeyError as error:
            raise TransferError(f"Mediendatei fehlt im Export: {filename}") from error
        staged = workdir / filename
        with archive.open(info) as source, staged.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
        if detect_media_type(staged) is None:
            raise TransferError(f"Keine gültige Mediendatei: {filename}")
        existing = media_dir() / filename
        if existing.is_file():
            if file_sha256(existing) == file_sha256(staged):
                renamed[filename] = filename
                continue
            new_name = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
        else:
            new_name = filename
        target = media_dir() / new_name
        staged.replace(target)
        created.append(target)
        renamed[filename] = new_name
    return renamed, created


def import_playlist(path: Path) -> dict:
    """Import a playlist export as a new, inactive playlist."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise TransferError("Die Datei ist kein gültiges ZIP-Archiv.") from error
    with archive, tempfile.TemporaryDirectory(prefix=".playlist-import-", dir=data_dir()) as temporary:
        manifest = _read_manifest(archive)
        total = sum(info.file_size for info in archive.infolist())
        if total > MAX_ARCHIVE_BYTES:
            raise TransferError("Der Export ist zu groß.")
        ensure_free_space(media_dir(), total)
        filenames = [str(name) for name in dict.fromkeys(manifest["files"])]
        renamed, created = _extract_media(archive, filenames, Path(temporary))

        def remap(source):
            name = media_filename(source)
            if name is None:
                return source
            if name not in renamed:
                raise TransferError(f"Mediendatei fehlt im Export: {name}")
            return f"/media/{renamed[name]}"

        skipped = 0
        try:
            with connect() as connection:
                playlist = manifest["playlist"]
                name = _unique_name(connection, str(playlist["name"]))
                weekdays = playlist.get("schedule_weekdays")
                playlist_id = connection.execute(
                    """INSERT INTO playlists(name, active, schedule_enabled, schedule_start, schedule_end,
                       schedule_weekdays, schedule_daily_start, schedule_daily_end) VALUES (?, 0, ?, ?, ?, ?, ?, ?)""",
                    (name, int(bool(playlist.get("schedule_enabled"))), playlist.get("schedule_start"),
                     playlist.get("schedule_end"), weekdays if isinstance(weekdays, str) else None,
                     playlist.get("schedule_daily_start"), playlist.get("schedule_daily_end")),
                ).lastrowid
                media_ids: dict[int, int] = {}
                for item in manifest["media_library"]:
                    values = {key: item.get(key) for key in LIBRARY_FIELDS}
                    for key in ("source", "original_source", "thumbnail_source"):
                        values[key] = remap(values[key])
                    values["category"] = values["category"] or ""
                    existing = connection.execute(
                        "SELECT id FROM media_library WHERE source = ?", (values["source"],)
                    ).fetchone()
                    if existing:
                        media_ids[item["ref"]] = existing["id"]
                        continue
                    media_ids[item["ref"]] = connection.execute(
                        f"INSERT INTO media_library({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                        tuple(values.values()),
                    ).lastrowid
                for item in manifest["content"]:
                    if item.get("kind") not in CONTENT_KINDS:
                        skipped += 1
                        continue
                    values = {key: item.get(key) for key in CONTENT_FIELDS}
                    values["source"] = remap(values["source"])
                    logo = _logo(values["text_config"])
                    if logo:
                        config = json.loads(values["text_config"])
                        config["logo_source"] = remap(logo)
                        values["text_config"] = json.dumps(config)
                    values["media_id"] = media_ids.get(item.get("media_ref"))
                    values["playlist_id"] = playlist_id
                    connection.execute(
                        f"INSERT INTO content({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                        tuple(values.values()),
                    )
        except (sqlite3.Error, TypeError, KeyError, ValueError) as error:
            for target in created:
                target.unlink(missing_ok=True)
            if isinstance(error, TransferError):
                raise
            raise TransferError("Der Export enthält ungültige Einträge.") from error
    return {
        "id": playlist_id, "name": name,
        "content_count": len(manifest["content"]) - skipped, "skipped": skipped,
        "media_files": len(filenames), "new_media_files": len(created),
        "missing_files": manifest.get("missing_files") or [],
        "schedule_enabled": bool(playlist.get("schedule_enabled")),
    }
