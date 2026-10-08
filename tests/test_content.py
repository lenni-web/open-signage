"""Inhalte: Webseiten, Livestreams, Uploads, PDFs, Videos und Freitext."""

import pytest
import shutil
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from open_signage.main import app
from open_signage.media_probe import evaluate_video_probe
from open_signage.upload_security import detect_media_type, ensure_free_space
from open_signage.version import __version__

from helpers import VALID_PNG


def test_upload_detection_uses_content_and_preserves_disk_reserve(tmp_path: Path, monkeypatch):
    image = tmp_path / "angeblich.pdf"
    image.write_bytes(VALID_PNG)
    assert detect_media_type(image) == "image/png"
    monkeypatch.setattr(
        "open_signage.upload_security.shutil.disk_usage",
        lambda _path: shutil._ntuple_diskusage(total=10_000_000_000, used=9_700_000_000, free=300_000_000),
    )
    with pytest.raises(HTTPException) as error:
        ensure_free_space(tmp_path)
    assert error.value.status_code == 507


def test_health_and_website_crud(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": __version__}
        assert client.get("/api/content").status_code == 401
        assert client.post(
            "/api/system/login", json={"password": "open-signage"}
        ).status_code == 200

        created = client.post(
            "/api/content/website",
            json={
                "name": "Beispiel",
                "url": "https://example.org",
                "duration_seconds": 15,
            },
        )
        assert created.status_code == 201
        item = created.json()
        assert item["kind"] == "website"
        assert item["enabled"] is True

        updated = client.patch(
            f"/api/content/{item['id']}",
            json={"duration_seconds": 20, "enabled": False},
        )
        assert updated.status_code == 200
        assert updated.json()["duration_seconds"] == 20
        assert updated.json()["enabled"] is False

        assert client.get("/api/player/content").json() == []
        assert client.delete(f"/api/content/{item['id']}").status_code == 204


def test_invalid_website_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/website",
            json={"name": "Falsch", "url": "javascript:alert(1)", "duration_seconds": 10},
        )
        assert response.status_code == 422


def test_owncast_stream_is_normalized_and_can_enable_sound(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/stream",
            json={
                "name": "Live",
                "url": "https://stream.mg-stade.de/embed/video?initiallyMuted=true",
                "duration_seconds": 3600,
                "muted": True,
            },
        )
        assert response.status_code == 201
        item = response.json()
        assert item["kind"] == "stream"
        assert item["source"] == "https://stream.mg-stade.de/hls/stream.m3u8"
        assert item["muted"] is True

        updated = client.patch(f"/api/content/{item['id']}", json={"muted": False})
        assert updated.status_code == 200
        assert updated.json()["muted"] is False


def test_compatible_mp4_probe_has_no_warning():
    result = evaluate_video_probe(
        ".mp4",
        {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )
    assert result["compatible"] is True
    assert result["warnings"] == []


def test_incompatible_mp4_probe_explains_supported_format():
    result = evaluate_video_probe(
        ".mp4",
        {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc"},
                {"codec_type": "audio", "codec_name": "ac3"},
            ],
        },
    )
    assert result["compatible"] is False
    assert any("H.264" in warning for warning in result["warnings"])
    assert any("AAC" in warning for warning in result["warnings"])
    assert "WebM" in result["recommendation"]


def test_video_upload_returns_compatibility_result(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    compatibility = {
        "checked": True,
        "compatible": False,
        "warnings": ["Für zuverlässige Wiedergabe H.264/AVC verwenden."],
        "recommendation": "Empfohlen: MP4 mit H.264/AVC und AAC.",
    }
    monkeypatch.setattr("open_signage.routes.content.validate_video", lambda _path: compatibility)

    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/upload",
            data={"duration_seconds": "10", "muted": "false", "play_to_end": "true"},
            files={"file": ("video.mp4", b"\x00\x00\x00\x18ftypisom0000", "video/mp4")},
        )

    assert response.status_code == 201
    assert response.json()["kind"] == "video"
    assert response.json()["muted"] is False
    assert response.json()["play_to_end"] is True
    assert response.json()["media_id"] is not None
    assert response.json()["compatibility"] == compatibility
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        library = client.get("/api/media-library").json()
    assert len(library) == 1
    assert library[0]["id"] == response.json()["media_id"]
    assert library[0]["name"] == "video.mp4"


def test_website_default_duration_is_twelve_seconds(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/website",
            json={"name": "Web", "url": "https://example.org"},
        )
    assert response.status_code == 201
    assert response.json()["duration_seconds"] == 12


def test_pdf_can_be_uploaded_and_deleted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        uploaded = client.post(
            "/api/content/upload",
            data={"duration_seconds": "20"},
            files={
                "file": (
                    "hinweis.pdf",
                    b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF",
                    "application/pdf",
                )
            },
        )
        assert uploaded.status_code == 201
        item = uploaded.json()
        assert item["kind"] == "pdf"
        stored = tmp_path / "media" / Path(item["source"]).name
        assert stored.exists()

        served = client.get(item["source"])
        assert served.headers["cache-control"] == "private, max-age=31536000, immutable"

        deleted = client.delete(f"/api/content/{item['id']}")
        assert deleted.status_code == 204
        assert not stored.exists()


def test_invalid_pdf_is_rejected_and_removed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        response = client.post(
            "/api/content/upload",
            files={"file": ("falsch.pdf", b"kein pdf", "application/pdf")},
        )

    assert response.status_code == 415
    assert list((tmp_path / "media").iterdir()) == []


def test_text_content_can_be_previewed_by_player_edited_and_deleted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post(
            "/api/content/text",
            data={
                "name": "Begrüßung",
                "headline": "Willkommen",
                "subheadline": "Im Foyer",
                "body": "Die Veranstaltung beginnt um 18 Uhr.",
                "shadow_box": "true",
                "shadow_intensity": "dark",
                "text_align": "center",
                "vertical_position": "bottom",
                "text_color": "#eeeeee",
                "accent_color": "#ffcc00",
                "font_size": "large",
                "font_family": "serif",
                "background_dim": "35",
                "focus_x": "25",
                "focus_y": "70",
                "template_style": "elegant",
                "duration_seconds": "12",
            },
            files={
                "background": ("foyer.png", VALID_PNG, "image/png"),
                "logo": ("logo.png", VALID_PNG, "image/png"),
            },
        )
        assert created.status_code == 201
        item = created.json()
        assert item["kind"] == "text"
        assert item["text_config"]["headline"] == "Willkommen"
        assert item["text_config"]["shadow_box"] is True
        assert item["text_config"]["shadow_intensity"] == "dark"
        assert item["text_config"]["text_align"] == "center"
        assert item["text_config"]["vertical_position"] == "bottom"
        assert item["text_config"]["background_dim"] == 35
        assert item["text_config"]["focus_x"] == 25
        logo = tmp_path / "media" / Path(item["text_config"]["logo_source"]).name
        assert logo.exists()
        old_background = tmp_path / "media" / Path(item["source"]).name
        assert old_background.exists()
        assert client.get("/api/player/content").json()[0]["id"] == item["id"]

        edited = client.post(
            f"/api/content/{item['id']}/text",
            data={
                "name": "Neue Begrüßung",
                "headline": "Guten Abend",
                "subheadline": "",
                "body": "Beginn um 19 Uhr.",
                "duration_seconds": "20",
            },
        )
        assert edited.status_code == 200
        assert edited.json()["text_config"]["headline"] == "Guten Abend"
        assert edited.json()["text_config"]["shadow_box"] is False
        assert edited.json()["text_config"]["shadow_intensity"] == "medium"
        assert edited.json()["source"] == item["source"]
        assert edited.json()["text_config"]["logo_source"] == item["text_config"]["logo_source"]

        assert client.delete(f"/api/content/{item['id']}").status_code == 204
        assert not old_background.exists()
        assert not logo.exists()


def test_text_content_requires_background_and_some_text(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        wrong_image = client.post(
            "/api/content/text",
            data={"name": "Text", "headline": "Titel", "subheadline": "", "body": ""},
            files={"background": ("datei.pdf", b"pdf", "application/pdf")},
        )
        assert wrong_image.status_code == 415

        no_text = client.post(
            "/api/content/text",
            data={"name": "Leer", "headline": "", "subheadline": "", "body": ""},
            files={"background": ("bild.png", b"image", "image/png")},
        )
        assert no_text.status_code == 422
        assert not (tmp_path / "media").exists() or not list((tmp_path / "media").iterdir())

        invalid_intensity = client.post(
            "/api/content/text",
            data={
                "name": "Schatten",
                "headline": "Titel",
                "shadow_intensity": "maximum",
            },
            files={"background": ("bild.png", b"image", "image/png")},
        )
        assert invalid_intensity.status_code == 422


def test_text_content_supports_video_background(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "open_signage.routes.content.validate_video",
        lambda _path: {"checked": True, "video_codecs": ["h264"]},
    )
    with TestClient(app) as client:
        client.post("/api/system/login", json={"password": "open-signage"})
        created = client.post(
            "/api/content/text",
            data={"name": "Video-Hinweis", "headline": "Willkommen"},
            files={"background": ("loop.mp4", b"\x00\x00\x00\x18ftypisom0000", "video/mp4")},
        )
        assert created.status_code == 201
        item = created.json()
        assert item["text_config"]["background_kind"] == "video"
        assert item["source"].endswith(".mp4")
        assert (tmp_path / "media" / Path(item["source"]).name).exists()
