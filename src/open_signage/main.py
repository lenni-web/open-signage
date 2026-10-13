from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import forwarding, live
from .auth import device_mode, get_setting, set_setting
from .backup import automatic_backup_if_due
from .database import initialize, integrity_check_if_due
from .routes import (content, forwarding as forwarding_routes, live as live_routes, media_library, pages,
                     player, playlists, session, storage, sync, system)
from .routes.common import STATIC_DIR
from .sync import poll_controller_command, report_status_to_controller, safe_sync_from_controller
from .version import __version__


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    if not get_setting("device_role"):
        install_mode = os.environ.get("OPEN_SIGNAGE_MODE", "standalone")
        set_setting("device_role", install_mode if install_mode in {"standalone", "controller", "display"} else "standalone")
        controller_url = os.environ.get("OPEN_SIGNAGE_CONTROLLER_URL", "").strip()
        if controller_url: set_setting("controller_url", controller_url)
    device_mode()
    live.write_config()
    live.request_server_setup()
    integrity_check_if_due()
    await asyncio.to_thread(automatic_backup_if_due)
    async def database_maintenance() -> None:
        ticks = 0
        while True:
            await asyncio.sleep(60)
            ticks += 1
            if device_mode() == "display":
                await asyncio.to_thread(safe_sync_from_controller)
                await asyncio.to_thread(report_status_to_controller)
            if ticks >= 24 * 60:
                ticks = 0
                await asyncio.to_thread(integrity_check_if_due)
                await asyncio.to_thread(automatic_backup_if_due)
    async def controller_commands() -> None:
        # Displays fragen alle 10 Sekunden nach Befehlen des Controllers (Update, Neustart, Bildschirm).
        while True:
            await asyncio.sleep(10)
            if device_mode() == "display":
                await asyncio.to_thread(poll_controller_command)
    maintenance_task = asyncio.create_task(database_maintenance())
    command_task = asyncio.create_task(controller_commands())
    # Weiterleitung des OBS-Streams an RTMP-Ziele (z. B. Owncast).
    app.state.forwarding = forwarding.Manager(forwarding.TargetStore())
    app.state.forwarding.start()
    try:
        yield
    finally:
        maintenance_task.cancel()
        command_task.cancel()
        await app.state.forwarding.stop()


app = FastAPI(title="Open Signage", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
for module in (pages, player, system, sync, storage, session, playlists, content, media_library, live_routes,
               forwarding_routes):
    app.include_router(module.router)
