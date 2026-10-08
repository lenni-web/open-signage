"""Ausgelieferte Seiten, Verwaltungsoberfläche und Player-Skript."""

from fastapi.testclient import TestClient

from open_signage.main import app
from open_signage.version import __version__

from helpers import PROJECT_ROOT


ADMIN_SCRIPTS = ("core", "content", "library", "playlists", "live", "display", "system", "session")


def admin_scripts() -> str:
    return "\n".join(
        (PROJECT_ROOT / f"src/open_signage/static/admin/{module}.js").read_text(encoding="utf-8")
        for module in ADMIN_SCRIPTS
    )


def test_html_pages_version_static_assets_and_disable_document_cache():
    with TestClient(app) as client:
        admin = client.get("/")
        player = client.get("/player")
    assert admin.headers["cache-control"] == "no-store"
    assert player.headers["cache-control"] == "no-store"
    assert f"/static/style.css?v={__version__}" in admin.text
    for module in ADMIN_SCRIPTS:
        assert f"/static/admin/{module}.js?v={__version__}" in admin.text
    assert f"/static/player.js?v={__version__}" in player.text


def test_admin_contains_system_navigation_and_update_controls():
    admin = (PROJECT_ROOT / "src/open_signage/static/admin.html").read_text(
        encoding="utf-8"
    )

    assert 'data-page="system-page"' in admin
    assert 'data-page="settings-page"' in admin
    assert 'id="settings-content"' in admin
    assert '<h2 class="page-title">System</h2>' in admin
    assert 'id="wlan-info"' in admin
    assert 'id="ethernet-info"' in admin
    assert 'class="network-overview"' in admin
    assert 'id="system-update"' in admin
    assert 'id="login-form"' in admin
    assert 'id="screen-settings-form"' in admin
    assert 'id="application-update"' in admin
    assert 'id="login-screen"' in admin
    assert 'id="admin-app" hidden' in admin
    assert 'id="logout"' in admin
    assert 'data-page="library-page"' in admin
    assert 'id="media-library"' in admin
    assert 'id="text-library-image"' in admin
    assert 'name="shadow_intensity"' in admin
    assert 'id="playlist-select"' in admin
    assert 'id="playlist-create"' in admin
    assert 'id="library-search"' in admin
    assert 'id="library-bulk-add"' in admin
    assert 'id="monitoring-summary"' in admin
    assert 'id="monitoring-refresh"' in admin
    assert 'id="display-control-form"' in admin
    assert 'name="resolution_mode"' in admin
    assert 'id="display-resolution-status"' in admin
    assert 'name="transition_ms"' in admin
    assert 'id="live-obs-guide"' in admin
    player_html = (PROJECT_ROOT / "src/open_signage/static/player.html").read_text(encoding="utf-8")
    assert 'id="player-pair-form"' in player_html
    assert 'name="password"' in player_html

    admin_script = admin_scripts()
    assert "function organizeAdministrationPages()" in admin_script
    assert "async function openSettingsPage()" in admin_script
    assert 'id="admin-clock"' in admin
    assert 'data-display-action="on"' in admin
    assert 'data-display-action="off"' in admin
    assert 'id="add-content-type"' in admin
    assert 'video/mp4,video/webm' in admin
    admin_js = admin_scripts()
    assert "preview.poster = item.thumbnail_source" in admin_js
    assert "Optimal konvertieren" in admin_js
    assert admin.count('class="card update-card collapsible-card"') == 2
    assert 'class="card system-overview collapsible-card"' in admin
    assert 'value="12"' in admin


def test_player_skips_unknown_content_kinds():
    player = (PROJECT_ROOT / "src/open_signage/static/player.js").read_text(encoding="utf-8")
    assert "Unbekannter Inhaltstyp" in player
