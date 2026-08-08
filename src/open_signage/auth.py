from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response

from .database import connect

DEFAULT_PASSWORD = "open-signage"
SESSION_COOKIE = "open_signage_session"
SESSION_LIFETIME = timedelta(hours=12)
_sessions: dict[str, datetime] = {}


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def _setting(key: str) -> str | None:
    with connect() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def screen_name() -> str:
    return _setting("screen_name") or "Open Signage"


def verify_password(password: str) -> bool:
    encoded = _setting("admin_password")
    if encoded is None:
        encoded = _password_hash(DEFAULT_PASSWORD)
        set_setting("admin_password", encoded)
    try:
        _, salt_hex, digest_hex = encoded.split("$", 2)
        candidate = _password_hash(password, bytes.fromhex(salt_hex)).split("$", 2)[2]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest_hex)


def require_system_login(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    expires = _sessions.get(token)
    if not expires or expires <= datetime.now(UTC):
        _sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="Anmeldung erforderlich")


def create_session(response: Response) -> None:
    token = secrets.token_urlsafe(32)
    _sessions[token] = datetime.now(UTC) + SESSION_LIFETIME
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True, samesite="strict",
    )


def destroy_session(request: Request, response: Response) -> None:
    _sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)
    response.delete_cookie(SESSION_COOKIE, samesite="strict")


def change_password(password: str, response: Response) -> None:
    set_setting("admin_password", _password_hash(password))
    _sessions.clear()
    create_session(response)
