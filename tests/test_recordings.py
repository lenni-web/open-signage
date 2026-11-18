"""Aufnahmen der Live-Übertragungen."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_signage import live, recordings
from open_signage.auth import set_setting
from open_signage.database import initialize
from open_signage.main import app

from helpers import PROJECT_ROOT


def _recording(name: str, age_seconds: float = 3600, content: bytes = b"mp4") -> Path:
    folder = recordings.recordings_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    moment = time.time() - age_seconds
    os.utime(path, (moment, moment))
    return path


def test_controller_records_every_broadcast_unless_switched_off(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    config = live.render_config()
    assert "    record: yes" in config and "    recordDeleteAfter: 0s" in config
    assert f'recordPath: "{tmp_path}/recordings/%path/%Y-%m-%d_%H-%M-%S-%f"' in config
    assert "    recordFormat: fmp4" in config
    live.set_recording_enabled(False)
    assert "    record: no" in live.render_config()

    set_setting("device_role", "display")
    assert "record" not in live.render_config()
    set_setting("controller_url", "http://controller.local:8080")
    set_setting("live_read_password", "secret")
    assert "record" not in live.render_config()


def test_only_the_latest_recordings_are_kept(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    monkeypatch.setattr(recordings, "stream_status", lambda: {"available": True})
    names = [f"2026-11-{day:02d}_10-00-00-000000.mp4" for day in range(1, 13)]
    for index, name in enumerate(names):
        _recording(name, age_seconds=(13 - index) * 86400)
    recordings.converted_path(names[0]).parent.mkdir(parents=True, exist_ok=True)
    recordings.converted_path(names[0]).write_bytes(b"aac")
    (recordings.recordings_dir() / "notizen.txt").write_text("bleibt")

    assert recordings.cleanup() == 2
    remaining = sorted(path.name for path in recordings.recordings_dir().glob("*.mp4"))
    assert remaining == sorted(names[2:])
    assert not recordings.converted_path(names[0]).exists()
    assert (recordings.recordings_dir() / "notizen.txt").exists()

    # Eine laufende Aufnahme wird nie gelöscht, auch wenn sie rechnerisch zu alt wäre.
    _recording("2026-10-01_10-00-00-000000.mp4", age_seconds=1)
    assert recordings.cleanup(keep=0) == 10
    assert [path.name for path in recordings.recordings_dir().glob("*.mp4")] == ["2026-10-01_10-00-00-000000.mp4"]


def test_recordings_api_lists_downloads_and_deletes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(recordings, "stream_status", lambda: {"available": True})
    with TestClient(app) as client:
        assert client.get("/api/recordings").status_code == 401
        client.post("/api/system/login", json={"password": "open-signage"})
        assert client.get("/api/recordings").json() == {"available": True, "enabled": True, "keep": 10, "recordings": []}
        finished = _recording("2026-11-15_10-00-00-123456.mp4", content=b"aufnahme")
        _recording("2026-11-15_11-00-00-000000.mp4", age_seconds=2)

        listed = client.get("/api/recordings").json()["recordings"]
        assert [(item["name"], item["active"]) for item in listed] == [
            ("2026-11-15_11-00-00-000000.mp4", True), ("2026-11-15_10-00-00-123456.mp4", False)]
        assert listed[1]["size_bytes"] == 8 and listed[1]["conversion"] is None

        download = client.get("/api/recordings/2026-11-15_10-00-00-123456.mp4/download")
        assert download.content == b"aufnahme"
        assert download.headers["content-disposition"] == \
            "attachment; filename*=utf-8''Livestream%202026-11-15%2010-00.mp4"
        assert client.get("/api/recordings/2026-11-15_10-00-00-123456.mp4/download?audio=aac").status_code == 409
        assert client.get("/api/recordings/..%2Fmediamtx.yml/download").status_code == 404
        assert client.get("/api/recordings/fremd.mp4/download").status_code == 404

        assert client.delete("/api/recordings/2026-11-15_11-00-00-000000.mp4").status_code == 409
        assert client.post("/api/recordings/2026-11-15_11-00-00-000000.mp4/convert").status_code == 409
        assert client.delete("/api/recordings/2026-11-15_10-00-00-123456.mp4").status_code == 204
        assert not finished.exists()

        assert client.put("/api/recordings/settings", json={"enabled": False}).json() == {"enabled": False}
        assert "    record: no" in live.config_path().read_text(encoding="utf-8")
        set_setting("device_role", "display")
        assert client.get("/api/recordings").json()["available"] is False


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg fehlt")
def test_recording_audio_is_converted_to_aac(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    initialize()
    monkeypatch.setattr(recordings, "stream_status", lambda: {"available": False})
    source = _recording("2026-11-15_10-00-00-000000.mp4")
    created = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "libopus",
         "-movflags", "+frag_keyframe+empty_moov", str(source)],
        capture_output=True, check=False)
    if created.returncode != 0:
        pytest.skip("ffmpeg ohne libx264/libopus")
    assert recordings.start_conversion(source.name, background=False) == {
        "status": "done", "size_bytes": recordings.converted_path(source.name).stat().st_size}
    codecs = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0",
         str(recordings.converted_path(source.name))], capture_output=True, text=True, check=True).stdout.split()
    assert codecs == ["h264", "aac"]
    assert recordings.list_recordings()[0]["conversion"]["status"] == "done"
    assert recordings.download_name(source.name, True) == "Livestream 2026-11-15 10-00 (AAC-Ton).mp4"


def test_mediamtx_may_write_recordings():
    system_action = (PROJECT_ROOT / "deploy/open-signage-system-action").read_text(encoding="utf-8")
    assert "ReadWritePaths=-/var/lib/open-signage/recordings" in system_action
    assert "install -d -o open-signage -g open-signage -m 0750 /var/lib/open-signage/recordings" in system_action
