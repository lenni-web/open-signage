"""Stream-Weiterleitung an RTMP-Ziele (übernommen aus dem Projekt „Stream-Verteiler“)."""

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_signage import forwarding
from open_signage.auth import get_setting, set_setting
from open_signage.database import initialize
from open_signage.forwarding import (LOG_LINES, Manager, TargetError, TargetStore, build_command, clean_target,
                                     output_url, parse_progress, probe, redact)
from open_signage.main import app

RTMP = {"name": "Owncast", "url": "rtmp://owncast.example/live/", "secret": "key123"}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    return TargetStore()


def login(client):
    client.post("/api/system/login", json={"password": "open-signage"})


def test_url_validation_and_masking():
    target = clean_target(RTMP)
    assert output_url(target) == "rtmp://owncast.example/live/key123"
    assert redact("Server returned 401 for rtmp://x/live/key123", target) == "Server returned 401 for rtmp://x/live/***"
    for bad in ({**RTMP, "url": "http://x"}, {**RTMP, "url": "rtmp://"}, {**RTMP, "name": " "},
                {**RTMP, "audio_mode": "kaputt"}):
        with pytest.raises(TargetError):
            clean_target(bad)


def test_command_copies_video_and_converts_audio_per_mode():
    def cmd(**extra):
        return build_command(clean_target({**RTMP, **extra}))

    std = cmd()
    assert std[std.index("-i") + 1] == "rtsp://127.0.0.1:8554/live"
    assert std[std.index("-c:v") + 1] == "copy" and std[std.index("-c:a") + 1] == "aac"
    assert "-af" not in std and std[std.index("-b:a") + 1] == "160k" and std[-1] == "rtmp://owncast.example/live/key123"
    assert "nobuffer" not in std  # Owncast puffert ohnehin; normale Pufferung ist stabiler
    gaps = cmd(audio_mode="gaps")
    assert gaps[gaps.index("-af") + 1] == "aresample=async=1:min_hard_comp=0.02:first_pts=0"
    assert "async=1000" not in " ".join(gaps)  # dehnender Filter (klang schief) darf nie verwendet werden
    regular = cmd(audio_mode="regular")
    assert regular[regular.index("-af") + 1] == "asetpts=N/SR/TB"
    hq = cmd(audio_mode="hq")
    assert hq[hq.index("-b:a") + 1] == "256k"
    passthrough = cmd(audio_aac=False, audio_mode="gaps")
    assert passthrough[passthrough.index("-c") + 1] == "copy" and "-af" not in passthrough


def test_store_persists_in_database_and_keeps_secret(store):
    target = store.upsert_target(RTMP)
    store.upsert_target({"name": "Neu", "secret": "", "audio_mode": "gaps"}, target["id"])
    reloaded = TargetStore().get_target(target["id"])
    assert reloaded["name"] == "Neu" and reloaded["secret"] == "key123" and reloaded["audio_mode"] == "gaps"
    assert "key123" in get_setting("forwarding_targets")
    assert store.delete_target(target["id"]) and TargetStore().targets == []


def test_api_requires_login_hides_secrets_and_is_blocked_on_displays(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/forwarding").status_code == 401
        assert client.post("/api/forwarding/targets", json=RTMP).status_code == 401
        login(client)
        created = client.post("/api/forwarding/targets", json=RTMP)
        assert created.status_code == 201
        target = created.json()
        assert "secret" not in target and target["has_secret"] is True
        assert target["status"]["state"] in ("waiting", "starting")
        state = client.get("/api/forwarding")
        assert "key123" not in state.text and state.json()["ingest"]["available"] is False
        assert client.post("/api/forwarding/targets", json={**RTMP, "url": "http://x"}).status_code == 422
        updated = client.put(f"/api/forwarding/targets/{target['id']}", json={"name": "Owncast HQ", "audio_mode": "hq"})
        assert updated.json()["name"] == "Owncast HQ"
        assert client.put("/api/forwarding/targets/nope", json=RTMP).status_code == 404
        assert client.get(f"/api/forwarding/targets/{target['id']}/log").json()["lines"]
        assert client.post(f"/api/forwarding/targets/{target['id']}/restart").status_code == 200
        assert client.post("/api/forwarding/test", json={"id": "nope"}).status_code == 404
        assert client.post("/api/forwarding/test", json={"name": "x", "url": "http://x"}).status_code == 422

        set_setting("device_role", "display")
        assert client.post("/api/forwarding/targets", json=RTMP).status_code == 403
        set_setting("device_role", "standalone")
        assert client.delete(f"/api/forwarding/targets/{target['id']}").status_code == 204
        assert client.get("/api/forwarding").json()["targets"] == []


def test_displays_never_forward(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    monkeypatch.setattr("open_signage.live.stream_status", lambda: {"server_running": True, "available": True})
    assert forwarding.ingest_status()["available"] is True
    set_setting("device_role", "display")
    assert forwarding.ingest_status()["available"] is False


def test_runner_follows_ingest_and_restarts(store):
    """Ein Ersatz-„ffmpeg“ läuft nur, solange OBS sendet, und wird nach einem Absturz neu gestartet."""
    state = {"available": False}
    started = []

    def fake_cmd(target):
        started.append(target["name"])
        return [sys.executable, "-c", "import time; time.sleep(30)"]

    async def scenario():
        store.upsert_target(RTMP)
        mgr = Manager(store, command_builder=fake_cmd, status_fn=lambda: dict(state))
        mgr.ingest = dict(state)
        await mgr.reconcile()
        target = store.targets[0]
        await asyncio.sleep(0.7)
        assert mgr.target_status(target)["state"] == "waiting" and not started
        state["available"] = True
        mgr.ingest = dict(state)
        await asyncio.sleep(1.0)
        assert started and mgr.target_status(target)["state"] in ("starting", "running")
        proc = mgr.runners[target["id"]].proc
        proc.kill()
        await asyncio.sleep(2.5)
        assert len(started) >= 2 and mgr.runners[target["id"]].proc is not proc
        store.targets[0]["enabled"] = False
        await mgr.reconcile()
        assert mgr.target_status(target)["state"] == "disabled"
        await mgr.stop()

    run(scenario())


def test_log_masks_secrets_survives_restart_and_is_cleaned_on_delete(store):
    secret = "geheim123"

    def failing_cmd(target):
        # Wie ein ffmpeg, das die Zugangsdaten in seiner Fehlermeldung ausgibt.
        code = f"import sys; sys.stderr.write('Server returned 401 for rtmp://x/live/{secret}\\n'); sys.exit(1)"
        return [sys.executable, "-c", code]

    async def scenario():
        target = store.upsert_target({**RTMP, "secret": secret})
        mgr = Manager(store, command_builder=failing_cmd, status_fn=lambda: {"available": True})
        mgr.ingest = {"available": True}
        await mgr.reconcile()
        await asyncio.sleep(2.0)
        lines = mgr.get_log(target["id"])
        text = "\n".join(line["msg"] for line in lines)
        assert secret not in text and "***" in text
        assert any(line["level"] == "error" and "401" in line["msg"] for line in lines)
        assert any("neuer Versuch" in line["msg"] for line in lines)
        before = len(lines)
        store.upsert_target({"name": "Umbenannt"}, target["id"])  # neuer Runner, Protokoll bleibt
        await mgr.reconcile()
        assert any("Konfiguration geändert" in line["msg"] for line in mgr.get_log(target["id"]))
        assert len(mgr.get_log(target["id"])) > before
        store.delete_target(target["id"])
        await mgr.reconcile()
        assert mgr.get_log(target["id"]) == []
        await mgr.stop()

    run(scenario())


def test_log_is_bounded(store):
    mgr = Manager(store, status_fn=lambda: {"available": False})
    for index in range(LOG_LINES + 50):
        mgr.log("x", "info", f"Zeile {index}")
    lines = mgr.get_log("x")
    assert len(lines) == LOG_LINES and lines[-1]["msg"] == f"Zeile {LOG_LINES + 49}"


def test_hanging_ffmpeg_is_stopped_when_signal_stays_gone(store, monkeypatch):
    """Ein ffmpeg, das trotz fehlendem Signal weiterläuft, darf die Verbindung zum Ziel nicht offen halten."""
    monkeypatch.setattr("open_signage.forwarding.NO_SIGNAL_STOP_AFTER", 1.0)
    state = {"available": True}

    async def scenario():
        target = store.upsert_target(RTMP)
        mgr = Manager(store, command_builder=lambda t: [sys.executable, "-c", "import time; time.sleep(60)"],
                      status_fn=lambda: dict(state))
        mgr.ingest = dict(state)
        await mgr.reconcile()
        await asyncio.sleep(1.0)
        proc = mgr.runners[target["id"]].proc
        assert proc.returncode is None
        state["available"] = False
        mgr.ingest = dict(state)
        await asyncio.sleep(0.5)
        assert proc.returncode is None  # kurzer Aussetzer: noch nicht beenden
        await asyncio.sleep(2.0)
        assert proc.returncode is not None
        assert mgr.target_status(target)["state"] == "waiting"
        assert any("kein OBS-Signal" in line["msg"] for line in mgr.get_log(target["id"]))
        state["available"] = True
        mgr.ingest = dict(state)
        await asyncio.sleep(1.5)
        assert mgr.runners[target["id"]].proc is not proc and mgr.runners[target["id"]].proc.returncode is None
        await mgr.stop()

    run(scenario())


def test_parse_progress():
    assert parse_progress({"bitrate": " 2487.3kbits/s", "fps": "29.97"}) == {"bitrate_kbps": 2487.3, "fps": 29.97}
    assert parse_progress({"bitrate": "N/A", "fps": "0.00"})["bitrate_kbps"] is None
    assert parse_progress({}) == {"bitrate_kbps": None, "fps": None}


FAKE_PROGRESS = (
    "import sys,time\n"
    "for i in range({n}):\n"
    "    print('fps=30.0\\nbitrate=2500.0kbits/s\\nprogress=continue', flush=True)\n"
    "    time.sleep(0.2)\n"
    "time.sleep(60)\n"
)


def test_progress_is_shown_and_stalled_ffmpeg_is_restarted(store, monkeypatch):
    monkeypatch.setattr("open_signage.forwarding.STALL_AFTER", 1.0)
    starts = []

    def cmd(target):
        starts.append(1)
        # Erster Lauf meldet nur kurz Fortschritt und hängt dann; spätere Läufe melden weiter.
        n = 5 if len(starts) == 1 else 400
        return [sys.executable, "-c", FAKE_PROGRESS.format(n=n)]

    async def scenario():
        target = store.upsert_target(RTMP)
        mgr = Manager(store, command_builder=cmd, status_fn=lambda: {"available": True})
        mgr.ingest = {"available": True}
        await mgr.reconcile()
        await asyncio.sleep(0.7)
        assert mgr.target_status(target)["bitrate_kbps"] == 2500.0
        await asyncio.sleep(3.5)
        assert len(starts) >= 2
        assert "kein Fortschritt" in " ".join(line["msg"] for line in mgr.get_log(target["id"]))
        await mgr.stop()

    run(scenario())


def test_probe_rtmp_handshake_and_non_rtmp():
    async def rtmp(reader, writer):
        await reader.readexactly(1537)
        writer.write(b"\x03" + b"\0" * 1536)
        await writer.drain()
        writer.close()

    async def not_rtmp(reader, writer):
        await reader.readexactly(1537)
        writer.close()

    async def scenario():
        good = await asyncio.start_server(rtmp, "127.0.0.1", 0)
        bad = await asyncio.start_server(not_rtmp, "127.0.0.1", 0)
        p1, p2 = good.sockets[0].getsockname()[1], bad.sockets[0].getsockname()[1]
        a = await probe(clean_target({**RTMP, "url": f"rtmp://127.0.0.1:{p1}/live"}))
        b = await probe(clean_target({**RTMP, "url": f"rtmp://127.0.0.1:{p2}/live"}))
        closed = await probe(clean_target({**RTMP, "url": "rtmp://127.0.0.1:1/live"}))
        good.close()
        bad.close()
        return a, b, closed

    a, b, closed = run(scenario())
    assert a["checks"][-1]["ok"] is None  # Stream-Key nur als Hinweis
    assert a["checks"][-2]["ok"] is True
    assert not b["ok"] and "geschlossen" in b["checks"][-2]["detail"]
    assert not closed["ok"] and "abgelehnt" in closed["checks"][-1]["detail"]
