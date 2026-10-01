"""Shared helpers for files stored in the media directory."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlparse

# Hashes are cached per path and invalidated by size or modification time, so
# repeated sync polls only stat unchanged files instead of reading them again.
_hash_cache: dict[str, tuple[int, int, str]] = {}
_hash_lock = threading.Lock()


def media_filename(source: str | None) -> str | None:
    """Return the media directory filename for a local /media/ source."""
    if not source:
        return None
    parsed = urlparse(source)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/media/"):
        return None
    return Path(parsed.path).name or None


def referenced_media_files(connection: sqlite3.Connection) -> set[str]:
    """All media filenames referenced by the library, content items and text logos."""
    names = set()
    for row in connection.execute("SELECT source, original_source, thumbnail_source FROM media_library"):
        names.update(media_filename(source) for source in row)
    for row in connection.execute("SELECT source, text_config FROM content"):
        names.add(media_filename(row["source"]))
        if row["text_config"]:
            try:
                names.add(media_filename(json.loads(row["text_config"]).get("logo_source")))
            except (ValueError, AttributeError):
                pass
    names.discard(None)
    return names


def file_sha256(path: Path) -> str:
    stat = path.stat()
    key = str(path)
    with _hash_lock:
        cached = _hash_cache.get(key)
    if cached and cached[:2] == (stat.st_size, stat.st_mtime_ns):
        return cached[2]
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024): digest.update(chunk)
    remember_sha256(path, digest.hexdigest(), stat)
    return digest.hexdigest()


def remember_sha256(path: Path, digest: str, stat=None) -> None:
    stat = stat or path.stat()
    with _hash_lock:
        _hash_cache[str(path)] = (stat.st_size, stat.st_mtime_ns, digest)
