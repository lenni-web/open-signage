from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response

from .database import connect

DEFAULT_PASSWORD = "open-signage"
SESSION_COOKIE = "open_signage_session"
PLAYER_COOKIE = "open_signage_player"
PLAYER_COOKIE_LIFETIME = timedelta(days=400)
SESSION_LIFETIME = timedelta(hours=12)
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_BLOCK = timedelta(minutes=15)
MAX_LOGIN_FAILURES = 5
LOCAL_PLAYER_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
    "169.254.0.0/16", "fc00::/7", "fe80::/10", "::1/128",
))
LOOPBACK_NETWORKS = tuple(ipaddress.ip_network(network) for network in ("127.0.0.0/8", "::1/128"))
DISPLAY_WRITE_PATHS = {
    "/api/system/password", "/api/system/logout", "/api/system/device",
    "/api/system/device/sync", "/api/system/action", "/api/system/update",
    "/api/system/application-update", "/api/system/display-control/action",
    "/api/system/player-access",
}


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


def get_setting(key: str, default: str | None = None) -> str | None:
    return _setting(key) or default


def screen_name() -> str:
    return _setting("screen_name") or "Open Signage"


def device_mode() -> str:
    value = _setting("device_role") or "standalone"
    migrated = {"master": "controller", "slave": "display"}.get(value, value)
    if migrated not in {"standalone", "controller", "display"}: migrated = "standalone"
    if migrated != value: set_setting("device_role", migrated)
    return migrated


def verify_password(password: str) -> bool:
    encoded = _setting("admin_password")
    if encoded is None:
        initial_password = os.environ.get("OPEN_SIGNAGE_INITIAL_PASSWORD", DEFAULT_PASSWORD)
        encoded = _password_hash(initial_password)
        set_setting("admin_password", encoded)
        required = os.environ.get("OPEN_SIGNAGE_REQUIRE_INITIAL_PASSWORD_CHANGE", "1")
        set_setting("password_change_required", "1" if required != "0" else "0")
    try:
        _, salt_hex, digest_hex = encoded.split("$", 2)
        candidate = _password_hash(password, bytes.fromhex(salt_hex)).split("$", 2)[2]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest_hex)


def password_change_required() -> bool:
    return _setting("password_change_required") == "1"


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def ensure_login_allowed(request: Request) -> None:
    now = datetime.now(UTC)
    with connect() as connection:
        row = connection.execute(
            "SELECT blocked_until FROM login_attempts WHERE client_key = ?", (client_key(request),)
        ).fetchone()
    if row and row["blocked_until"] and datetime.fromisoformat(row["blocked_until"]) > now:
        remaining = max(1, int((datetime.fromisoformat(row["blocked_until"]) - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Zu viele fehlgeschlagene Anmeldungen. Bitte später erneut versuchen.",
            headers={"Retry-After": str(remaining)},
        )


def record_login_failure(request: Request) -> None:
    now = datetime.now(UTC)
    key = client_key(request)
    with connect() as connection:
        row = connection.execute(
            "SELECT failed_count, window_started FROM login_attempts WHERE client_key = ?", (key,)
        ).fetchone()
        count = 1
        started = now
        if row:
            try:
                previous_start = datetime.fromisoformat(row["window_started"])
                if now - previous_start <= LOGIN_WINDOW:
                    count = row["failed_count"] + 1
                    started = previous_start
            except ValueError:
                pass
        blocked_until = (now + LOGIN_BLOCK).isoformat() if count >= MAX_LOGIN_FAILURES else None
        connection.execute(
            "INSERT INTO login_attempts(client_key, failed_count, window_started, blocked_until) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(client_key) DO UPDATE SET "
            "failed_count=excluded.failed_count, window_started=excluded.window_started, "
            "blocked_until=excluded.blocked_until",
            (key, count, started.isoformat(), blocked_until),
        )


def clear_login_failures(request: Request) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM login_attempts WHERE client_key = ?", (client_key(request),))


def player_token() -> str:
    token = _setting("player_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        set_setting("player_token", token)
    return token


def _client_in(request: Request, networks: tuple) -> bool:
    if not request.client:
        return False
    try:
        address = ipaddress.ip_address(request.client.host.split("%", 1)[0])
    except ValueError:
        return request.client.host == "testclient"
    return any(address in network for network in networks)


def local_player_client(request: Request) -> bool:
    return _client_in(request, LOCAL_PLAYER_NETWORKS)


def lan_player_access_enabled() -> bool:
    return _setting("player_lan_access") != "0"


def automatic_player_client(request: Request) -> bool:
    """Der lokale Kiosk ist immer berechtigt, andere private Netze nur bei aktiver LAN-Freigabe."""
    if _client_in(request, LOOPBACK_NETWORKS):
        return True
    return lan_player_access_enabled() and local_player_client(request)


def set_player_cookie(response: Response) -> None:
    # Bild-, Video- und PDF-Elemente können keinen Authorization-Header senden.
    response.set_cookie(
        PLAYER_COOKIE, player_token(), max_age=int(PLAYER_COOKIE_LIFETIME.total_seconds()),
        httponly=True, samesite="strict",
    )


def require_player(request: Request) -> None:
    authorization = request.headers.get("Authorization", "")
    supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    if supplied and hmac.compare_digest(supplied, player_token()):
        return
    cookie = request.cookies.get(PLAYER_COOKIE, "")
    if cookie and hmac.compare_digest(cookie, player_token()):
        return
    session = request.cookies.get(SESSION_COOKIE, "")
    if session:
        with connect() as connection:
            row = connection.execute(
                "SELECT expires_at FROM admin_sessions WHERE token_hash = ?",
                (hashlib.sha256(session.encode()).hexdigest(),),
            ).fetchone()
        if row and datetime.fromisoformat(row["expires_at"]) > datetime.now(UTC):
            return
    raise HTTPException(status_code=401, detail="Ungültige Player-Anmeldung")


def require_system_login(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect() as connection:
        row = connection.execute(
            "SELECT expires_at FROM admin_sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        connection.execute(
            "DELETE FROM admin_sessions WHERE expires_at <= ?", (datetime.now(UTC).isoformat(),)
        )
    if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Anmeldung erforderlich")
    if (
        password_change_required()
        and request.method not in {"GET", "HEAD"}
        and request.url.path not in {"/api/system/password", "/api/system/logout"}
    ):
        raise HTTPException(
            status_code=403,
            detail="Das Initialpasswort muss zuerst auf der Systemseite geändert werden.",
        )
    if (
        device_mode() == "display"
        and request.method not in {"GET", "HEAD"}
        and request.url.path not in DISPLAY_WRITE_PATHS
    ):
        raise HTTPException(
            status_code=403,
            detail="Dieses Gerät wird im Display-Modus vollständig vom Controller verwaltet.",
        )


def session_is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return False
    with connect() as connection:
        row = connection.execute(
            "SELECT expires_at FROM admin_sessions WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
    return bool(row and datetime.fromisoformat(row["expires_at"]) > datetime.now(UTC))


def create_session(response: Response) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + SESSION_LIFETIME
    with connect() as connection:
        connection.execute(
            "INSERT INTO admin_sessions(token_hash, expires_at) VALUES (?, ?)",
            (hashlib.sha256(token.encode()).hexdigest(), expires.isoformat()),
        )
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True, samesite="strict",
    )


def destroy_session(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    with connect() as connection:
        connection.execute(
            "DELETE FROM admin_sessions WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
    response.delete_cookie(SESSION_COOKIE, samesite="strict")


def change_password(password: str, response: Response) -> None:
    set_setting("admin_password", _password_hash(password))
    set_setting("password_change_required", "0")
    with connect() as connection:
        connection.execute("DELETE FROM admin_sessions")
    create_session(response)
