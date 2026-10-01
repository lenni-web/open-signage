"""Login, logout, password and screen name settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import (change_password, clear_login_failures, create_session, destroy_session,
                    device_mode, ensure_login_allowed, password_change_required,
                    record_login_failure, require_system_login, screen_name,
                    session_is_authenticated, set_setting, verify_password)

router = APIRouter()


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ScreenSettings(BaseModel):
    screen_name: str = Field(min_length=1, max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.get("/api/settings")
def get_public_settings():
    return {"screen_name": screen_name()}


@router.get("/api/system/session")
def system_session(request: Request):
    if not session_is_authenticated(request):
        return {"authenticated": False}
    return {"authenticated": True, "screen_name": screen_name(), "device_mode": device_mode(),
            "password_change_required": password_change_required()}


@router.post("/api/system/login")
def system_login(payload: LoginRequest, request: Request, response: Response):
    ensure_login_allowed(request)
    if not verify_password(payload.password):
        record_login_failure(request)
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    clear_login_failures(request)
    create_session(response)
    return {"authenticated": True, "screen_name": screen_name(),
            "password_change_required": password_change_required()}


@router.post("/api/system/logout", status_code=204)
def system_logout(request: Request, response: Response):
    destroy_session(request, response)


@router.patch("/api/system/settings")
def update_system_settings(payload: ScreenSettings, _: None = Depends(require_system_login)):
    name = payload.screen_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Der Bildschirmname darf nicht leer sein")
    set_setting("screen_name", name)
    return {"screen_name": name}


@router.post("/api/system/password")
def update_system_password(payload: PasswordChange, response: Response, _: None = Depends(require_system_login)):
    if not verify_password(payload.current_password):
        raise HTTPException(status_code=400, detail="Das aktuelle Passwort ist falsch")
    change_password(payload.new_password, response)
    return {"changed": True}
