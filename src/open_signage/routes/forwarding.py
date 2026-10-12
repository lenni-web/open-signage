"""Stream-Weiterleitung: RTMP-Ziele verwalten, Status, Protokoll und Verbindungstest."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import forwarding
from ..auth import require_system_login

router = APIRouter(dependencies=[Depends(require_system_login)])


def _manager(request: Request) -> forwarding.Manager:
    return request.app.state.forwarding


def _public(manager: forwarding.Manager, target: dict[str, Any]) -> dict[str, Any]:
    shown = {key: value for key, value in target.items() if key != "secret"}
    shown["has_secret"] = bool(target.get("secret"))
    shown["status"] = manager.target_status(target)
    return shown


@router.get("/api/forwarding")
def forwarding_state(request: Request):
    manager = _manager(request)
    return {"ingest": {key: manager.ingest.get(key, False) for key in ("server_running", "available")},
            "targets": [_public(manager, target) for target in manager.store.targets]}


@router.post("/api/forwarding/targets", status_code=201)
async def create_target(body: dict[str, Any], request: Request):
    manager = _manager(request)
    try:
        target = manager.store.upsert_target(body)
    except forwarding.TargetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await manager.reconcile()
    return _public(manager, target)


@router.put("/api/forwarding/targets/{target_id}")
async def update_target(target_id: str, body: dict[str, Any], request: Request):
    manager = _manager(request)
    try:
        target = manager.store.upsert_target(body, target_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Ziel nicht gefunden") from error
    except forwarding.TargetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await manager.reconcile()
    return _public(manager, target)


@router.delete("/api/forwarding/targets/{target_id}", status_code=204)
async def delete_target(target_id: str, request: Request):
    manager = _manager(request)
    if not manager.store.delete_target(target_id):
        raise HTTPException(status_code=404, detail="Ziel nicht gefunden")
    await manager.reconcile()


@router.post("/api/forwarding/targets/{target_id}/restart")
async def restart_target(target_id: str, request: Request):
    manager = _manager(request)
    if not manager.store.get_target(target_id):
        raise HTTPException(status_code=404, detail="Ziel nicht gefunden")
    await manager.restart(target_id)
    return {"restarted": True}


@router.get("/api/forwarding/targets/{target_id}/log")
def target_log(target_id: str, request: Request):
    manager = _manager(request)
    if not manager.store.get_target(target_id):
        raise HTTPException(status_code=404, detail="Ziel nicht gefunden")
    return {"lines": manager.get_log(target_id)}


@router.post("/api/forwarding/test")
async def test_target(body: dict[str, Any], request: Request):
    """Testet ein gespeichertes Ziel (id) oder die noch nicht gespeicherten Formularwerte."""
    manager = _manager(request)
    existing = manager.store.get_target(str(body.get("id"))) if body.get("id") else None
    if body.get("id") and not existing:
        raise HTTPException(status_code=404, detail="Ziel nicht gefunden")
    try:
        target = forwarding.clean_target(body, existing)
    except forwarding.TargetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await forwarding.probe(target)
