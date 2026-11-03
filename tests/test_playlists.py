"""Playlists und Zeitpläne für Inhalte und Playlists."""

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage.main import app
from open_signage.routes.common import scheduled_now

from helpers import VALID_PNG


def test_content_schedule_controls_player_playlist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post(
            "/api/content/website",
            json={"name": "Termin", "url": "https://example.org"},
        ).json()
        future = client.patch(
            f"/api/content/{created['id']}",
            json={"schedule_start": "2099-01-01T12:00:00+00:00"},
        )
        assert future.status_code == 200
        assert client.get("/api/player/content").json() == []

        cleared = client.patch(
            f"/api/content/{created['id']}", json={"clear_schedule": True}
        )
        assert cleared.status_code == 200
        assert cleared.json()["schedule_start"] is None
        assert len(client.get("/api/player/content").json()) == 1


def test_overnight_and_weekday_schedules():
    monday_late = datetime.fromisoformat("2026-08-10T23:30:00+02:00")
    tuesday_early = datetime.fromisoformat("2026-08-11T01:30:00+02:00")
    item = {
        "schedule_start": None,
        "schedule_end": None,
        "schedule_weekdays": [0, 1],
        "schedule_daily_start": "22:00",
        "schedule_daily_end": "02:00",
    }
    assert scheduled_now(item, monday_late)
    assert scheduled_now(item, tuesday_early)
    item["schedule_weekdays"] = [2]
    assert not scheduled_now(item, monday_late)


def test_multiple_playlists_are_isolated_and_switch_player(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        first = client.post(
            "/api/content/website", json={"name": "Standardinhalt", "url": "https://one.example"}
        ).json()
        default_playlist = next(item for item in client.get("/api/playlists").json() if item["active"])

        second_playlist = client.post("/api/playlists", json={"name": "Abend"})
        assert second_playlist.status_code == 201
        second_id = second_playlist.json()["id"]
        client.post(f"/api/playlists/{second_id}/activate")
        assert client.get("/api/content").json() == []
        second = client.post(
            "/api/content/website", json={"name": "Abendinhalt", "url": "https://two.example"}
        ).json()
        assert [item["id"] for item in client.get("/api/player/content").json()] == [second["id"]]
        assert client.delete(f"/api/playlists/{second_id}").status_code == 409

        client.post(f"/api/playlists/{default_playlist['id']}/activate")
        assert [item["id"] for item in client.get("/api/player/content").json()] == [first["id"]]
        assert client.delete(f"/api/playlists/{second_id}").status_code == 204
        assert len(client.get("/api/playlists").json()) == 1


def test_playlist_schedule_can_override_manual_playlist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        client.post("/api/content/website", json={"name": "Standard", "url": "https://example.org", "duration_seconds": 12})
        scheduled = client.post("/api/playlists", json={"name": "Abend"}).json()
        client.post(f"/api/playlists/{scheduled['id']}/activate")
        special = client.post("/api/content/website", json={"name": "Geplant", "url": "https://example.net", "duration_seconds": 12}).json()
        client.post("/api/playlists/1/activate")
        response = client.patch(f"/api/playlists/{scheduled['id']}/schedule", json={
            "schedule_enabled": True, "schedule_weekdays": [datetime.now().astimezone().weekday()],
            "schedule_daily_start": "00:00", "schedule_daily_end": "23:59",
        })
        assert response.status_code == 200
        shown = client.get("/api/player/content").json()
    assert [item["id"] for item in shown] == [special["id"]]


def _create_exportable_playlist(client) -> int:
    playlist = client.post("/api/playlists", json={"name": "Gottesdienst"}).json()
    client.post(f"/api/playlists/{playlist['id']}/activate")
    client.patch(f"/api/playlists/{playlist['id']}/schedule", json={
        "schedule_enabled": True, "schedule_weekdays": [6],
        "schedule_daily_start": "10:00", "schedule_daily_end": "12:00",
    })
    media = client.post("/api/media-library", files={"file": ("Plakat.png", VALID_PNG, "image/png")}).json()
    client.post(f"/api/media-library/{media['id']}/playlist", json={"duration_seconds": 15})
    text = client.post(
        "/api/content/text",
        data={"name": "Begrüßung", "headline": "Willkommen", "duration_seconds": "12"},
        files={"background": ("foyer.png", VALID_PNG, "image/png"), "logo": ("logo.png", VALID_PNG, "image/png")},
    )
    assert text.status_code == 201
    client.post("/api/content/website", json={"name": "Termine", "url": "https://example.org"})
    return playlist["id"]


def test_playlist_export_and_import_with_media(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path / "quelle"))
    with TestClient(app) as client:
        assert client.get("/api/playlists/1/export").status_code == 401
        client.post("/api/system/login", json={"password": "open-signage"})
        playlist_id = _create_exportable_playlist(client)
        exported = client.get(f"/api/playlists/{playlist_id}/export")
        assert client.get("/api/playlists/999/export").status_code == 404
    assert exported.status_code == 200
    assert exported.headers["content-disposition"] == "attachment; filename*=utf-8''Playlist%20Gottesdienst.zip"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert sorted(name for name in archive.namelist() if name.startswith("media/")) == \
            sorted(f"media/{name}" for name in manifest["files"])
    assert len(manifest["content"]) == 3
    assert not list((tmp_path / "quelle").glob(".playlist-export-*"))

    target = tmp_path / "ziel"
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(target))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        imported = client.post("/api/playlists/import",
                               files={"file": ("export.zip", exported.content, "application/zip")})
        again = client.post("/api/playlists/import",
                            files={"file": ("export.zip", exported.content, "application/zip")})
        playlists = {item["name"]: item for item in client.get("/api/playlists").json()}
        library = client.get("/api/media-library").json()
        client.post(f"/api/playlists/{imported.json()['id']}/activate")
        contents = client.get("/api/content").json()

    assert imported.status_code == 201, imported.text
    result = imported.json()
    assert result["name"] == "Gottesdienst"
    assert result["content_count"] == 3 and result["skipped"] == 0
    assert result["schedule_enabled"] is True
    assert result["new_media_files"] == len(manifest["files"])
    assert again.json()["name"] == "Gottesdienst (Import)"
    assert again.json()["new_media_files"] == 0
    imported_playlist = playlists["Gottesdienst"]
    assert imported_playlist["active"] is False
    assert imported_playlist["schedule_weekdays"] == [6]
    assert imported_playlist["schedule_daily_start"] == "10:00"
    assert sorted(item["name"] for item in library) == ["Plakat.png", "foyer.png"]
    assert [item["name"] for item in contents] == ["Plakat.png", "Begrüßung", "Termine"]
    plakat = next(item for item in library if item["name"] == "Plakat.png")
    assert contents[0]["media_id"] == plakat["id"] and contents[0]["duration_seconds"] == 15
    text = contents[1]
    assert text["text_config"]["headline"] == "Willkommen"
    assert text["media_id"] == next(item["id"] for item in library if item["name"] == "foyer.png")
    for source in (text["source"], text["text_config"]["logo_source"], plakat["original_source"]):
        assert (target / "media" / Path(source).name).is_file()


def test_playlist_import_rejects_invalid_archives(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))

    def archive(manifest: dict, files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as output:
            output.writestr("manifest.json", json.dumps(manifest))
            for name, data in files.items():
                output.writestr(name, data)
        return buffer.getvalue()

    base = {"format": "open-signage-playlist", "format_version": 1, "playlist": {"name": "X"},
            "media_library": [], "content": []}
    cases = [
        b"kein zip",
        archive({"format": "etwas anderes"}, {}),
        archive({**base, "files": ["../evil.png"]}, {"media/../evil.png": VALID_PNG}),
        archive({**base, "files": ["seite.html"]}, {"media/seite.html": b"<html>"}),
        archive({**base, "files": ["fake.png"]}, {"media/fake.png": b"<html>"}),
        archive({**base, "files": ["fehlt.png"]}, {}),
        archive({**base, "files": [], "content": [{"name": "Bild", "kind": "image", "source": "/media/x.png"}]}, {}),
        archive({**base, "files": ["ok.png"], "content": [{"name": "Bild", "kind": "image", "source": "/media/ok.png",
                                                            "duration_seconds": 0}]}, {"media/ok.png": VALID_PNG}),
    ]
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        responses = [client.post("/api/playlists/import", files={"file": ("x.zip", data, "application/zip")})
                     for data in cases]
        playlists = client.get("/api/playlists").json()
        future = client.post("/api/playlists/import", files={"file": ("x.zip", archive(
            {**base, "files": [], "content": [{"name": "Neu", "kind": "kalender", "source": "x"}]}, {}), "application/zip")})

    assert [response.status_code for response in responses] == [422] * len(cases)
    assert [item["name"] for item in playlists] == ["Standard"]
    assert not (tmp_path / "media" / "ok.png").exists()
    assert future.status_code == 201 and future.json()["skipped"] == 1
