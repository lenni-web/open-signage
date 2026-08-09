from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .database import connect, data_dir, database_path, media_dir

CONFIG_FILES = ("display-control.json",)


def backup_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(exist_ok=True)
    return path


def _safe_name(path: Path) -> bool:
    return not path.is_absolute() and ".." not in path.parts


def create_backup(include_media: bool = False, automatic: bool = False) -> dict:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"open-signage-{stamp}{'-auto' if automatic else ''}.zip"
    target = backup_dir() / name
    with tempfile.TemporaryDirectory(prefix="open-signage-backup-") as temporary:
        snapshot = Path(temporary) / "open-signage.sqlite3"
        with connect() as source, sqlite3.connect(snapshot) as destination:
            source.backup(destination)
        with sqlite3.connect(snapshot) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Datenbankkopie ist nicht integer")
        manifest = {"format": 1, "created_at": datetime.now(UTC).isoformat(),
                    "include_media": include_media}
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "database/open-signage.sqlite3")
            archive.writestr("manifest.json", json.dumps(manifest))
            for filename in CONFIG_FILES:
                path = data_dir() / filename
                if path.is_file(): archive.write(path, f"config/{filename}")
            if include_media:
                for path in media_dir().iterdir():
                    if path.is_file(): archive.write(path, f"media/{path.name}")
    rotate_backups()
    return backup_info(target)


def backup_info(path: Path) -> dict:
    stat = path.stat()
    return {"name": path.name, "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()}


def list_backups() -> list[dict]:
    return [backup_info(path) for path in sorted(backup_dir().glob("*.zip"), reverse=True)]


def rotate_backups() -> None:
    automatic = sorted(backup_dir().glob("*-auto.zip"), reverse=True)
    keep = set(automatic[:7])
    weekly: set[tuple[int, int]] = set()
    for path in automatic:
        date = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        week = date.isocalendar()[:2]
        if week not in weekly and len(weekly) < 4:
            weekly.add(week); keep.add(path)
    for path in automatic:
        if path not in keep: path.unlink(missing_ok=True)


def automatic_backup_if_due() -> dict | None:
    latest = next(iter(sorted(backup_dir().glob("*-auto.zip"), reverse=True)), None)
    if latest and datetime.now(UTC) - datetime.fromtimestamp(latest.stat().st_mtime, UTC) < timedelta(days=1):
        return None
    return create_backup(automatic=True)


def validate_backup(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = [Path(name) for name in archive.namelist()]
        if any(not _safe_name(name) for name in names): raise ValueError("Unsicherer Pfad im Backup")
        if Path("database/open-signage.sqlite3") not in names: raise ValueError("Datenbank fehlt")
        manifest = json.loads(archive.read("manifest.json"))
        with tempfile.TemporaryDirectory(prefix="open-signage-restore-") as temporary:
            extracted = Path(temporary) / "database.sqlite3"
            extracted.write_bytes(archive.read("database/open-signage.sqlite3"))
            with sqlite3.connect(extracted) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup-Datenbank ist beschädigt")
    return manifest


def restore_backup(path: Path) -> None:
    validate_backup(path)
    safety = create_backup(include_media=True)
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="open-signage-restore-") as temporary:
        temp = Path(temporary)
        archive.extractall(temp)
        replacement = temp / "database/open-signage.sqlite3"
        database_path().with_suffix(".sqlite3-wal").unlink(missing_ok=True)
        database_path().with_suffix(".sqlite3-shm").unlink(missing_ok=True)
        replacement.replace(database_path())
        for filename in CONFIG_FILES:
            source = temp / "config" / filename
            if source.is_file(): source.replace(data_dir() / filename)
        incoming_media = temp / "media"
        if incoming_media.is_dir():
            for item in incoming_media.iterdir():
                if item.is_file(): item.replace(media_dir() / item.name)
    # Keep the emergency backup discoverable; assignment documents intent.
    _ = safety
