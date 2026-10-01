"""Endpoints used by the fullscreen player."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import (clear_login_failures, ensure_login_allowed, local_player_client, player_token,
                    record_login_failure, require_player, verify_password)
from ..database import connect
from ..display_control import display_config
from .common import content_rows

router = APIRouter()


class PlayerPairRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class PlayerHeartbeat(BaseModel):
    state: str = Field(pattern=r"^(playing|idle|buffering|error)$")
    content_id: int | None = None
    content_name: str | None = Field(default=None, max_length=200)
    error: str | None = Field(default=None, max_length=500)


@router.post("/api/player/heartbeat", status_code=204)
def player_heartbeat(payload: PlayerHeartbeat, _: None = Depends(require_player)):
    with connect() as connection:
        previous = connection.execute("SELECT error FROM player_status WHERE id = 1").fetchone()
        if payload.error and (not previous or previous["error"] != payload.error):
            connection.execute(
                "INSERT INTO player_events(created_at, level, message, content_name) VALUES (?, 'error', ?, ?)",
                (datetime.now(UTC).isoformat(), payload.error, payload.content_name),
            )
        connection.execute(
            """INSERT INTO player_status(id, last_seen, state, content_id, content_name, error)
               VALUES (1, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen,
               state = excluded.state, content_id = excluded.content_id,
               content_name = excluded.content_name, error = excluded.error""",
            (datetime.now(UTC).isoformat(), payload.state, payload.content_id, payload.content_name, payload.error),
        )


@router.get("/api/player/bootstrap")
def player_bootstrap(request: Request):
    if not local_player_client(request):
        require_player(request)
    return {"token": player_token()}


@router.post("/api/player/pair")
def pair_player(payload: PlayerPairRequest, request: Request):
    ensure_login_allowed(request)
    if not verify_password(payload.password):
        record_login_failure(request)
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    clear_login_failures(request)
    return {"token": player_token()}


@router.get("/api/player/content")
def player_content(_: None = Depends(require_player)):
    return content_rows(enabled_only=True)


@router.get("/api/player/config")
def player_config(_: None = Depends(require_player)):
    return {"transition_ms": display_config().get("transition_ms", 4000)}
