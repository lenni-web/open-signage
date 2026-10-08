"""Mediathek: Uploads, Bildbearbeitung, Metadaten und Videokonvertierung."""

import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from open_signage.main import app

from helpers import VALID_PNG


def test_direct_image_upload_is_added_to_media_library(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/upload",
            files={"file": ("foto.png", VALID_PNG, "image/png")},
        )
        assert response.status_code == 201
        content = response.json()
        library = client.get("/api/media-library").json()

    assert content["kind"] == "image"
    assert content["media_id"] == library[0]["id"]
    assert content["source"] == library[0]["source"]
    assert library[0]["original_source"].endswith(".png")
    assert library[0]["thumbnail_source"].endswith("-thumb.jpg")


def test_media_library_reuses_files_for_playlist_and_text(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/media-library",
            files={"file": ("hintergrund.png", VALID_PNG, "image/png")},
        )
        assert uploaded.status_code == 201
        media = uploaded.json()
        assert client.get("/api/media-library").json()[0]["id"] == media["id"]
        stored = tmp_path / "media" / Path(media["source"]).name
        assert stored.exists()

        playlist = client.post(
            f"/api/media-library/{media['id']}/playlist",
            json={"duration_seconds": 15},
        )
        assert playlist.status_code == 201
        playlist_item = playlist.json()
        assert playlist_item["media_id"] == media["id"]

        text = client.post(
            "/api/content/text",
            data={
                "name": "Hinweis",
                "headline": "Hallo",
                "library_media_id": str(media["id"]),
            },
        )
        assert text.status_code == 201
        text_item = text.json()
        assert text_item["source"] == media["source"]
        assert text_item["media_id"] == media["id"]

        blocked = client.delete(f"/api/media-library/{media['id']}")
        assert blocked.status_code == 409
        assert client.delete(f"/api/content/{playlist_item['id']}").status_code == 204
        assert stored.exists()
        assert client.delete(f"/api/content/{text_item['id']}").status_code == 204
        assert client.delete(f"/api/media-library/{media['id']}").status_code == 204
        assert not stored.exists()


def test_media_library_is_protected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/media-library").status_code == 401
        assert client.post(
            "/api/media-library",
            files={"file": ("bild.jpg", b"image", "image/jpeg")},
        ).status_code == 401


def test_library_image_is_optimized_and_can_be_edited(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/media-library",
            files={"file": ("foto.png", VALID_PNG, "image/png")},
        )
        assert uploaded.status_code == 201
        media = uploaded.json()
        assert media["original_source"].endswith(".png")
        assert media["source"].endswith("-display.jpg")
        assert media["thumbnail_source"].endswith("-thumb.jpg")
        original = tmp_path / "media" / Path(media["original_source"]).name
        old_display = tmp_path / "media" / Path(media["source"]).name
        assert original.exists() and old_display.exists()

        edited = client.post(
            f"/api/media-library/{media['id']}/edit-image",
            json={
                "rotate": 90, "crop_16_9": True, "focus_x": 25, "focus_y": 75,
                "brightness": 1.1, "contrast": 1.2,
            },
        )
        assert edited.status_code == 200
        result = edited.json()
        assert result["source"] != media["source"]
        assert original.exists()
        assert not old_display.exists()


def test_library_metadata_rename_category_and_bulk_playlist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        ids = []
        for name in ("eins.png", "zwei.png"):
            uploaded = client.post(
                "/api/media-library", files={"file": (name, VALID_PNG, "image/png")}
            )
            ids.append(uploaded.json()["id"])
        updated = client.patch(
            f"/api/media-library/{ids[0]}", json={"name": "Bühne", "category": "Veranstaltung"}
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Bühne"
        assert updated.json()["category"] == "Veranstaltung"

        bulk = client.post(
            "/api/media-library/bulk-playlist",
            json={"media_ids": ids, "duration_seconds": 17},
        )
        assert bulk.status_code == 201
        assert len(bulk.json()["created_ids"]) == 2
        assert {item["duration_seconds"] for item in client.get("/api/content").json()} == {17}
        assert all(item["usage_count"] == 1 for item in client.get("/api/media-library").json())


def test_library_video_gets_thumbnail_and_can_be_transcoded(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    video = tmp_path / "input.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=blue:s=320x180:d=0.2", "-c:v", "mpeg4", str(video)],
        check=True,
    )
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/media-library",
            files={"file": ("clip.mp4", video.read_bytes(), "video/mp4")},
        )
        assert uploaded.status_code == 201
        media = uploaded.json()
        playlist = client.post(
            f"/api/media-library/{media['id']}/playlist",
            json={"duration_seconds": 12, "muted": False, "play_to_end": True},
        )
        assert playlist.status_code == 201
        assert playlist.json()["muted"] is False
        assert playlist.json()["play_to_end"] is True
        text = client.post(
            "/api/content/text",
            data={"name": "Video-Text", "headline": "Live", "library_media_id": str(media["id"])},
        )
        assert text.status_code == 201
        assert text.json()["text_config"]["background_kind"] == "video"
        assert text.json()["media_id"] == media["id"]
        assert media["thumbnail_source"].endswith("-video-thumb.jpg")
        assert media["metadata"]["width"] == 320
        converted = client.post(f"/api/media-library/{media['id']}/transcode")
        assert converted.status_code == 202
        for _ in range(100):
            job = client.get(f"/api/conversions/{converted.json()['job_id']}").json()
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert job["status"] == "completed", job
        converted_media = job["media"]
        assert converted_media["source"].endswith("-converted.mp4")
        assert converted_media["metadata"]["video_codec"] == "h264"
        first_converted = tmp_path / "media" / Path(converted_media["source"]).name
        assert first_converted.exists()
        converted_again = client.post(f"/api/media-library/{media['id']}/transcode")
        assert converted_again.status_code == 202
        for _ in range(100):
            second_job = client.get(f"/api/conversions/{converted_again.json()['job_id']}").json()
            if second_job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert second_job["status"] == "completed", second_job
        assert second_job["media"]["source"] != converted_media["source"]
        assert not first_converted.exists()
