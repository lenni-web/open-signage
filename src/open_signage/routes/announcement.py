"""Sofortmeldung für alle Player setzen und zurücknehmen."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..announcement import clear_announcement, local_announcement, set_announcement
from ..auth import require_system_login

router = APIRouter()


class AnnouncementCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500, pattern=r"\S")
    style: str = Field(default="top", pattern=r"^(top|bottom|fullscreen)$")
    minutes: int | None = Field(default=30, ge=1, le=24 * 60)


@router.get("/api/announcement")
def get_announcement(_: None = Depends(require_system_login)):
    return {"announcement": local_announcement()}


@router.put("/api/announcement")
def put_announcement(payload: AnnouncementCreate, _: None = Depends(require_system_login)):
    set_announcement(payload.text, payload.style, payload.minutes)
    return {"announcement": local_announcement()}


@router.delete("/api/announcement")
def delete_announcement(_: None = Depends(require_system_login)):
    clear_announcement()
    return {"announcement": None}
