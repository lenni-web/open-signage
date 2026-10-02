"""Live-Übertragung aus OBS: Status, Übernahme und WHEP-Weiterleitung für Player."""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import live
from ..auth import automatic_player_client, require_player, require_system_login

router = APIRouter()

MAX_SDP_BYTES = 64 * 1024
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class LiveTakeover(BaseModel):
    active: bool
    auto_end: bool = True
    sound: bool = True


def require_live_player(request: Request) -> None:
    if not automatic_player_client(request):
        require_player(request)


@router.get("/api/live")
def get_live(_: None = Depends(require_system_login)):
    return {
        **live.local_state(),
        "server_installed": live.server_installed(),
        "publish_path": f"/{live.LIVE_PATH}/whip",
        "publish_port": live.WEBRTC_PORT,
        "publish_token": f"obs:{live.publish_password()}",
    }


@router.post("/api/live/takeover")
def update_takeover(payload: LiveTakeover, _: None = Depends(require_system_login)):
    return live.set_takeover(payload.active, payload.auto_end, payload.sound)


@router.post("/api/live/password")
def regenerate_password(_: None = Depends(require_system_login)):
    return {"publish_token": f"obs:{live.regenerate_publish_password()}"}


@router.post("/api/live/setup", status_code=202)
def setup_server(_: None = Depends(require_system_login)):
    live.write_config()
    if not live.SYSTEM_ACTION_UNIT.is_file():
        raise HTTPException(status_code=409, detail="Die Einrichtung ist nur auf einem installierten Raspberry Pi möglich")
    if not live.request_server_setup(force=True):
        raise HTTPException(status_code=409, detail="Eine andere Systemaktion wird gerade ausgeführt")
    return {"queued": True}


@router.post("/api/player/live/whep", status_code=201)
async def whep_offer(request: Request, _: None = Depends(require_live_player)):
    offer = await request.body()
    if not offer or len(offer) > MAX_SDP_BYTES:
        raise HTTPException(status_code=400, detail="Ungültiges WebRTC-Angebot")
    status, headers, answer = await asyncio.to_thread(
        live.whep_request, "POST", f"/{live.LIVE_PATH}/whep", offer)
    if status != 201:
        raise HTTPException(status_code=503, detail="Live-Übertragung ist nicht verfügbar")
    location = headers.get("Location") or headers.get("location") or ""
    session = location.rstrip("/").rsplit("/", 1)[-1]
    response_headers = {}
    if SESSION_PATTERN.match(session):
        response_headers["Location"] = f"/api/player/live/session/{session}"
    return Response(answer, status_code=201, media_type="application/sdp", headers=response_headers)


@router.delete("/api/player/live/session/{session}", status_code=204)
async def whep_close(session: str, _: None = Depends(require_live_player)):
    if not SESSION_PATTERN.match(session):
        raise HTTPException(status_code=404)
    await asyncio.to_thread(live.whep_request, "DELETE", f"/{live.LIVE_PATH}/whep/{session}")
