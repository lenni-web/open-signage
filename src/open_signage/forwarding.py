"""Weiterleitung des OBS-Streams an RTMP-Ziele wie Owncast.

Übernommen aus dem Projekt „Stream-Verteiler“: Solange OBS an diesen Controller
sendet, läuft je aktivem Ziel ein ffmpeg, das das Video unverändert kopiert und
den Ton bei Bedarf von Opus nach AAC umwandelt. ffmpeg wird bei Fehlern mit
wachsender Pause neu gestartet, bei hängender Verbindung beendet und gestoppt,
wenn das Signal ausbleibt. Die gekoppelten Displays holen sich das Live-Bild
weiterhin selbst vom Controller; dafür ist keine Weiterleitung nötig.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shlex
import shutil
import ssl
import threading
import time
from collections import deque
from typing import Any, Callable, Deque
from urllib.parse import quote, urlparse

from . import live
from .auth import device_mode, get_setting, set_setting

SETTING_KEY = "forwarding_targets"
AUDIO_MODES = ("standard", "gaps", "regular", "hq")
FFMPEG = "ffmpeg"
STABLE_AFTER = 3.0  # Sekunden, ab denen ein Prozess als „läuft“ gilt
NO_SIGNAL_STOP_AFTER = 5.0  # Sekunden ohne OBS-Signal, nach denen ein noch laufendes ffmpeg beendet wird
STALL_AFTER = 15.0  # Sekunden ohne Fortschrittsmeldung, danach gilt die Verbindung als hängend
BACKOFF = (1, 2, 5, 10)
LOG_LINES = 300  # je Ziel; überlebt Neustarts von ffmpeg und Konfigurationsänderungen
PROBE_TIMEOUT = 4.0
ERROR_RE = re.compile(r"error|fail|refused|denied|unauthori[sz]ed|\b40[0-9]\b|\b50[0-9]\b|timed out|invalid|broken pipe|no such",
                      re.IGNORECASE)

# Ton-Verarbeitung (Opus -> AAC). Gemessen mit einer simulierten 50-ms-Tonlücke:
#  - ohne Filter bleibt die Lücke als Zeitsprung im Strom (kann als Ruckler hörbar sein),
#  - aresample=async=1:min_hard_comp=0.02 füllt sie mit Stille, die Tonhöhe bleibt gleich,
#  - aresample=async=1000 dehnt/staucht den Ton (Tonhöhe ~2 % daneben, klang „schief“) und wird nicht verwendet.
AUDIO_FILTERS = {
    "gaps": "aresample=async=1:min_hard_comp=0.02:first_pts=0",
    "regular": "asetpts=N/SR/TB",
}
AUDIO_BITRATES = {"hq": "256k"}


class TargetError(ValueError):
    pass


def clean_target(raw: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prüft und normalisiert ein Ziel. Ein leerer Stream-Key behält den bisherigen Wert."""
    existing = existing or {}
    name = str(raw.get("name", existing.get("name", ""))).strip()
    if not name:
        raise TargetError("Bitte einen Namen angeben.")
    url = str(raw.get("url", existing.get("url", ""))).strip().rstrip("/")
    if not url.startswith(("rtmp://", "rtmps://")) or not urlparse(url).hostname:
        raise TargetError("Die RTMP-Adresse muss mit rtmp:// oder rtmps:// beginnen und einen Server enthalten.")
    audio_mode = raw.get("audio_mode") or existing.get("audio_mode") or "standard"
    if audio_mode not in AUDIO_MODES:
        raise TargetError("Unbekannte Ton-Verarbeitung.")
    return {
        "id": existing.get("id") or secrets.token_hex(4),
        "type": "rtmp",
        "name": name[:60],
        "enabled": bool(raw.get("enabled", existing.get("enabled", True))),
        "url": url,
        "secret": str(raw.get("secret") or "").strip() or existing.get("secret", ""),
        "audio_mode": audio_mode,
        "audio_aac": bool(raw.get("audio_aac", existing.get("audio_aac", True))),
    }


def output_url(target: dict[str, Any]) -> str:
    return f"{target['url']}/{target['secret']}" if target.get("secret") else target["url"]


def redact(text: str, target: dict[str, Any]) -> str:
    secret = target.get("secret")
    if secret:
        for variant in (secret, quote(secret, safe="")):
            text = text.replace(variant, "***")
    return text


class TargetStore:
    """Ziele in der Open-Signage-Datenbank; dadurch in Backups enthalten."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        try:
            value = json.loads(get_setting(SETTING_KEY) or "[]")
        except ValueError:
            value = []
        self._targets: list[dict[str, Any]] = [t for t in value if isinstance(t, dict) and t.get("id")]

    @property
    def targets(self) -> list[dict[str, Any]]:
        return self._targets

    def _save(self) -> None:
        set_setting(SETTING_KEY, json.dumps(self._targets, ensure_ascii=False))

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        return next((t for t in self._targets if t["id"] == target_id), None)

    def upsert_target(self, raw: dict[str, Any], target_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            existing = self.get_target(target_id) if target_id else None
            if target_id and not existing:
                raise KeyError(target_id)
            target = clean_target(raw, existing)
            if existing:
                existing.clear()
                existing.update(target)
            else:
                self._targets.append(target)
            self._save()
            return target

    def delete_target(self, target_id: str) -> bool:
        with self._lock:
            before = len(self._targets)
            self._targets = [t for t in self._targets if t["id"] != target_id]
            self._save()
            return len(self._targets) != before


def build_command(target: dict[str, Any], ffmpeg: str = FFMPEG) -> list[str]:
    """ffmpeg-Aufruf: Das Video wird nie neu codiert, der Ton bei Bedarf nach AAC.

    Bei RTMP-Zielen wie Owncast zählt die Verzögerung nicht (HLS dort ohnehin
    mehrere Sekunden), daher wird normal gepuffert.
    """
    cmd = [ffmpeg, "-nostdin", "-nostats", "-hide_banner", "-loglevel", "warning", "-progress", "pipe:1",
           "-rtsp_transport", "tcp", "-i", f"rtsp://127.0.0.1:{live.RTSP_PORT}/{live.LIVE_PATH}", "-map", "0"]
    if target.get("audio_aac", True):
        mode = target.get("audio_mode", "standard")
        cmd += ["-c:v", "copy"]
        if mode in AUDIO_FILTERS:
            cmd += ["-af", AUDIO_FILTERS[mode]]
        cmd += ["-c:a", "aac", "-b:a", AUDIO_BITRATES.get(mode, "160k"), "-ar", "48000", "-ac", "2",
                "-f", "flv", "-flvflags", "no_duration_filesize"]
    else:
        cmd += ["-c", "copy", "-f", "flv", "-flvflags", "no_duration_filesize"]
    cmd.append(output_url(target))
    return cmd


def parse_progress(block: dict[str, str]) -> dict[str, Any]:
    """Wandelt einen `-progress`-Block in Zahlen um; nicht verfügbare Werte („N/A“) bleiben None."""
    bitrate = None
    match = re.match(r"\s*([\d.]+)\s*kbits/s", block.get("bitrate", ""))
    if match:
        bitrate = float(match.group(1))
    try:
        fps = float(block.get("fps", ""))
    except ValueError:
        fps = None
    return {"bitrate_kbps": bitrate, "fps": fps}


def ingest_status() -> dict[str, Any]:
    """OBS-Signal am Live-Server dieses Geräts; Displays leiten nicht weiter."""
    if device_mode() == "display":
        return {"server_running": False, "available": False}
    return live.stream_status()


def _fingerprint(target: dict[str, Any]) -> str:
    return json.dumps(target, sort_keys=True)


class Runner:
    def __init__(self, target: dict[str, Any], manager: "Manager"):
        self.target = target
        self.manager = manager
        self.state = "waiting"
        self.error = ""
        self.since = time.time()
        self.restarts = 0
        self.last_line = ""
        self.progress: dict[str, Any] = {}
        self.progress_at: float | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task[None] | None = None
        self.fingerprint = _fingerprint(target)

    def log(self, level: str, message: str) -> None:
        self.manager.log(self.target["id"], level, redact(message, self.target))

    def _set(self, state: str, error: str = "") -> None:
        if state != self.state:
            self.since = time.time()
        self.state, self.error = state, error

    async def _drain(self, stream: asyncio.StreamReader) -> None:
        try:
            async for line in stream:
                text = line.decode(errors="replace").strip()
                if text:
                    self.last_line = redact(text, self.target)
                    self.log("error" if ERROR_RE.search(text) else "ffmpeg", text)
        except ValueError:
            pass  # überlange Zeile ohne Zeilenumbruch: ignorieren

    async def _read_progress(self, stream: asyncio.StreamReader) -> None:
        """Liest ffmpegs `-progress`-Ausgabe (key=value-Blöcke, Ende jeweils `progress=…`)."""
        block: dict[str, str] = {}
        try:
            async for line in stream:
                key, _, value = line.decode(errors="replace").strip().partition("=")
                if not key:
                    continue
                block[key] = value
                if key == "progress":
                    self.progress = parse_progress(block)
                    self.progress_at = time.monotonic()
                    block = {}
        except ValueError:
            pass

    async def run(self) -> None:
        failures = 0
        while True:
            if not self.manager.ingest.get("available"):
                if self.state == "retry":
                    self.log("info", "OBS sendet nicht mehr – warte auf Signal.")
                elif not self.manager.logs.get(self.target["id"]):
                    self.log("info", "Warte auf OBS-Signal.")
                self._set("waiting")
                failures = 0
                while not self.manager.ingest.get("available"):
                    await asyncio.sleep(0.5)
                continue
            self._set("starting")
            self.last_line = ""
            self.progress, self.progress_at = {}, None
            started = time.monotonic()
            command = self.manager.command_builder(self.target)
            self.log("info", "OBS-Signal erkannt – starte ffmpeg.")
            if failures == 0:  # bei wiederholten Fehlversuchen nicht jedes Mal erneut protokollieren
                self.log("info", "$ " + shlex.join(command))
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            except OSError as exc:
                self._set("retry", f"ffmpeg konnte nicht gestartet werden: {exc}")
                self.log("error", self.error)
                await asyncio.sleep(5)
                continue
            drain = asyncio.ensure_future(self._drain(self.proc.stderr))
            progress_reader = asyncio.ensure_future(self._read_progress(self.proc.stdout))
            waiter = asyncio.ensure_future(self.proc.wait())
            no_signal_since: float | None = None
            try:
                while not waiter.done():
                    await asyncio.wait({waiter}, timeout=0.5)
                    if waiter.done():
                        break
                    if self.state != "running" and time.monotonic() - started >= STABLE_AFTER:
                        self._set("running")
                        self.log("info", "ffmpeg läuft stabil.")
                    # Meldet ffmpeg keinen Fortschritt mehr (Verbindung hängt), wird es beendet
                    # und über die normale Fehlerbehandlung neu gestartet.
                    if self.progress_at is not None and time.monotonic() - self.progress_at >= STALL_AFTER:
                        self.log("error", f"Seit {STALL_AFTER:.0f} s kein Fortschritt – Verbindung hängt, ffmpeg wird beendet.")
                        await self._terminate()
                        break
                    # Normalerweise beendet sich ffmpeg selbst, wenn OBS aufhört. Hängt es dennoch,
                    # würde die RTMP-Verbindung zum Ziel offen bleiben – dann wird es hier beendet.
                    if self.manager.ingest.get("available"):
                        no_signal_since = None
                    elif no_signal_since is None:
                        no_signal_since = time.monotonic()
                    elif time.monotonic() - no_signal_since >= NO_SIGNAL_STOP_AFTER:
                        self.log("info", f"Seit {NO_SIGNAL_STOP_AFTER:.0f} s kein OBS-Signal – ffmpeg wird beendet.")
                        await self._terminate()
                        break
            except asyncio.CancelledError:
                await self._terminate()
                self.log("info", "ffmpeg gestoppt.")
                raise
            finally:
                drain.cancel()
                progress_reader.cancel()
            lived = time.monotonic() - started
            failures = 0 if lived >= STABLE_AFTER * 3 else failures + 1
            self.restarts += 1
            code = self.proc.returncode
            if not self.manager.ingest.get("available"):
                self.log("info", f"OBS-Signal beendet – ffmpeg beendet (Code {code}).")
                continue  # normales Ende, kein Fehler
            delay = BACKOFF[min(failures, len(BACKOFF)) - 1] if failures else 1
            self._set("retry", self.last_line or f"ffmpeg beendet (Code {code})")
            self.log("error", f"ffmpeg beendet (Code {code}) – neuer Versuch in {delay} s.")
            await asyncio.sleep(delay)

    async def _terminate(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()

    def status(self) -> dict[str, Any]:
        fresh = self.progress_at is not None and time.monotonic() - self.progress_at < 5
        return {"state": self.state, "error": self.error, "since": self.since, "restarts": self.restarts,
                "bitrate_kbps": self.progress.get("bitrate_kbps") if fresh else None}


class Manager:
    def __init__(self, store: TargetStore, command_builder: Callable[[dict[str, Any]], list[str]] = build_command,
                 status_fn: Callable[[], dict[str, Any]] = ingest_status):
        self.store = store
        self.command_builder = command_builder
        self.status_fn = status_fn
        self.ingest: dict[str, Any] = {"server_running": False, "available": False}
        self.runners: dict[str, Runner] = {}
        self.logs: dict[str, Deque[dict[str, Any]]] = {}
        self._task: asyncio.Task[None] | None = None

    def log(self, target_id: str, level: str, message: str) -> None:
        self.logs.setdefault(target_id, deque(maxlen=LOG_LINES)).append(
            {"t": time.time(), "level": level, "msg": message})

    def get_log(self, target_id: str) -> list[dict[str, Any]]:
        return list(self.logs.get(target_id, ()))

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        for runner in list(self.runners.values()):
            await self._drop(runner)
        self.runners.clear()

    async def _drop(self, runner: Runner) -> None:
        if runner.task:
            runner.task.cancel()
            try:
                await runner.task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                # Ohne aktive Ziele muss der Live-Server nicht sekündlich befragt werden.
                if any(t.get("enabled") for t in self.store.targets) or self.runners:
                    self.ingest = await loop.run_in_executor(None, self.status_fn)
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:  # Der Überwacher darf nie sterben.
                pass
            await asyncio.sleep(1)

    async def reconcile(self) -> None:
        wanted = {t["id"]: t for t in self.store.targets if t.get("enabled")}
        for target_id, runner in list(self.runners.items()):
            target = wanted.get(target_id)
            if target is None or _fingerprint(target) != runner.fingerprint:
                await self._drop(runner)
                del self.runners[target_id]
                if self.store.get_target(target_id):
                    self.log(target_id, "info", "Deaktiviert." if target is None else "Konfiguration geändert – wird neu gestartet.")
        for target_id, target in wanted.items():
            if target_id not in self.runners:
                runner = Runner(dict(target), self)
                runner.task = asyncio.ensure_future(runner.run())
                self.runners[target_id] = runner
        for target_id in [k for k in self.logs if not self.store.get_target(k)]:
            del self.logs[target_id]  # Ziel wurde gelöscht

    async def restart(self, target_id: str) -> None:
        runner = self.runners.pop(target_id, None)
        if runner:
            await self._drop(runner)
            self.log(target_id, "info", "Manueller Neustart.")
        await self.reconcile()

    def target_status(self, target: dict[str, Any]) -> dict[str, Any]:
        runner = self.runners.get(target["id"])
        if runner is None:
            return {"state": "disabled", "error": "", "since": None, "restarts": 0, "bitrate_kbps": None}
        return runner.status()


# --- Verbindungstest, ohne dass Video gesendet wird --------------------------

def _check(label: str, ok: bool | None, detail: str) -> dict[str, Any]:
    # ok=None bedeutet: nicht prüfbar, nur ein Hinweis
    return {"label": label, "ok": ok, "detail": detail}


def _describe(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "Zeitüberschreitung, keine Antwort."
    if isinstance(exc, ConnectionRefusedError):
        return "Verbindung abgelehnt – läuft der Dienst und stimmt der Port?"
    if isinstance(exc, ssl.SSLError):
        return f"TLS-Fehler: {exc.reason or exc}"
    if isinstance(exc, OSError) and exc.errno in (8, 11001, -2, -3, -5):
        return "Hostname nicht auflösbar."
    return f"{type(exc).__name__}: {exc}"


async def probe(target: dict[str, Any]) -> dict[str, Any]:
    checks = [_check("ffmpeg", bool(shutil.which(FFMPEG)),
                     "Installiert." if shutil.which(FFMPEG) else "ffmpeg fehlt auf diesem Gerät (apt install ffmpeg).")]
    parsed = urlparse(target["url"])
    tls = parsed.scheme == "rtmps"
    host, port = parsed.hostname or "", parsed.port or (443 if tls else 1935)
    try:
        context = ssl.create_default_context() if tls else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host if tls else None), PROBE_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        checks.append(_check(f"Verbindung zu {host}:{port}", False, _describe(exc)))
        return {"ok": False, "checks": checks}
    checks.append(_check(f"Verbindung zu {host}:{port}", True, "Erreichbar" + (" (TLS gültig)." if tls else ".")))
    try:
        writer.write(b"\x03" + os.urandom(1536))  # C0 + C1
        await writer.drain()
        reply = await asyncio.wait_for(reader.readexactly(1 + 1536), PROBE_TIMEOUT)  # S0 + S1
        if reply[0] == 3:
            checks.append(_check("RTMP-Handshake", True, "Der Server antwortet als RTMP-Server."))
        else:
            checks.append(_check("RTMP-Handshake", False, "Unerwartete Antwort – kein RTMP-Server?"))
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        detail = ("Der Server hat die Verbindung ohne RTMP-Antwort geschlossen." if isinstance(exc, asyncio.IncompleteReadError)
                  else _describe(exc))
        checks.append(_check("RTMP-Handshake", False, detail))
    finally:
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), 1)
        except Exception:
            pass
    checks.append(_check("Stream-Key", None, "Kann erst beim echten Senden vom Server geprüft werden."))
    return {"ok": all(c["ok"] is not False for c in checks), "checks": checks}
