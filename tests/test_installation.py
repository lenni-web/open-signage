"""Version, Changelog, Installer, Updater und Systemvorlagen."""

import json

from open_signage.version import __version__

from helpers import PROJECT_ROOT


def test_current_version_is_documented_in_changelog():
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in changelog


def test_raspberry_pi_templates_have_expected_placeholders():
    service = (PROJECT_ROOT / "deploy/open-signage.service").read_text(encoding="utf-8")
    kiosk = (PROJECT_ROOT / "deploy/open-signage-kiosk").read_text(encoding="utf-8")

    assert "@@PORT@@" in service
    assert "Restart=on-failure" in service
    assert "@@PLAYER_URL@@" in kiosk
    assert "@@HEALTH_URL@@" in kiosk
    assert "--autoplay-policy=no-user-gesture-required" in kiosk
    assert "--ozone-platform=wayland" in kiosk
    assert "--user-data-dir" in kiosk
    assert "--disable-crash-reporter" in kiosk
    assert "DBUS_SESSION_BUS_ADDRESS" in kiosk
    assert "--disable-background-networking" in kiosk
    assert "--lang=de-DE" in kiosk
    assert "--accept-lang=de-DE,de" in kiosk
    assert "--disable-translate" in kiosk
    assert "Chromium wurde mit Status" in kiosk

    installer = (PROJECT_ROOT / "scripts/install-raspberry-pi.sh").read_text(
        encoding="utf-8"
    )
    assert "rpd-wayland-core" in installer
    assert "raspi-config nonint do_boot_behaviour B4" in installer
    assert 'KIOSK_USER="signage"' in installer
    assert "ffmpeg" in installer
    assert "--mode MODUS" in installer
    assert "--controller-url URL" in installer
    assert "OPEN_SIGNAGE_MODE" in installer
    assert 'chmod 0755 "${AUTOSTART_FILE}"' in installer
    assert "kiosk.log" in installer
    assert 's|@@KIOSK_USER@@|${KIOSK_USER}|g' in installer
    assert "locale-gen de_DE.UTF-8" in installer
    assert "open-signage-chromium-policy.json" in installer
    assert "open-signage-cursor-guard" in installer
    assert "open-signage-labwc-rc.xml" in installer
    assert "  wtype" in installer

    chromium_policy = json.loads(
        (PROJECT_ROOT / "deploy/open-signage-chromium-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert chromium_policy["TranslateEnabled"] is False

    labwc_config = (
        PROJECT_ROOT / "deploy/open-signage-labwc-rc.xml"
    ).read_text(encoding="utf-8")
    assert '<action name="HideCursor" />' in labwc_config
    assert '<action name="WarpCursor" x="-1" y="-1" />' in labwc_config
    cursor_guard = (
        PROJECT_ROOT / "deploy/open-signage-cursor-guard"
    ).read_text(encoding="utf-8")
    assert "while sleep 2" in cursor_guard
    assert 'output_states="$(wlopm 2>/dev/null)"' in cursor_guard
    assert "return 0" in cursor_guard
    assert "wtype -M alt -M logo -k h" in cursor_guard

    player_style = (
        PROJECT_ROOT / "src/open_signage/static/style.css"
    ).read_text(encoding="utf-8")
    assert ".player *" in player_style
    assert "cursor: none !important" in player_style
    assert ".player-transition-source.player-leaving" in player_style
    assert ".content-image" in player_style
    assert "isolation: isolate" in player_style
    assert "backface-visibility: hidden" in player_style
    player_script = (
        PROJECT_ROOT / "src/open_signage/static/player.js"
    ).read_text(encoding="utf-8")
    assert "function transitionTo(" in player_script
    assert "previousElements.forEach" in player_script
    assert "let transitionMs = 4000" in player_script
    assert 'fetch("/api/player/config"' in player_script
    assert 'fetch("/api/player/pair"' in player_script
    assert "PLAYER_TOKEN_KEY" in player_script
    assert "const WEBSITE_SETTLE_MS = 4000" in player_script
    assert "function settleAfter(" in player_script
    assert "function waitForVideoFrame(" in player_script
    assert "requestVideoFrameCallback" in player_script
    assert 'layer.className = "player-layer"' in player_script
    assert 'classList.add("player-transition-source")' in player_script
    assert 'classList.add("player-leaving")' in player_script


def test_update_service_is_installed_without_sudo_access():
    installer = (PROJECT_ROOT / "scripts/install-raspberry-pi.sh").read_text(
        encoding="utf-8"
    )
    update_service = (
        PROJECT_ROOT / "deploy/open-signage-update.service"
    ).read_text(encoding="utf-8")
    update_path = (PROJECT_ROOT / "deploy/open-signage-update.path").read_text(
        encoding="utf-8"
    )
    update_script = (
        PROJECT_ROOT / "deploy/open-signage-system-update"
    ).read_text(encoding="utf-8")

    assert "open-signage-update.path" in installer
    assert "  iw \\" in installer
    assert "ExecStart=/usr/local/sbin/open-signage-system-update" in update_service
    assert "PathExists=/var/lib/open-signage/update.request" in update_path
    assert "apt-get update &&" in update_script
    assert "apt-get upgrade -y" in update_script
    assert "sudo" not in update_script

    application_script = (
        PROJECT_ROOT / "deploy/open-signage-application-update"
    ).read_text(encoding="utf-8")
    application_service = (
        PROJECT_ROOT / "deploy/open-signage-application-update.service"
    ).read_text(encoding="utf-8")
    application_path = (
        PROJECT_ROOT / "deploy/open-signage-application-update.path"
    ).read_text(encoding="utf-8")
    assert "open-signage-application-update.path" in installer
    assert "git -C" in application_script
    assert "systemctl stop open-signage.service" in application_script
    assert "Healthcheck fehlgeschlagen" in application_script
    assert "ExecStart=/usr/local/sbin/open-signage-application-update" in application_service
    assert "ExecStartPre=/bin/sleep 2" in application_service
    assert "PathExists=/var/lib/open-signage/application-update.request" in application_path
    post_update = (PROJECT_ROOT / "deploy/open-signage-post-update").read_text(encoding="utf-8")
    assert 'bash "${release_dir}/deploy/open-signage-post-update" "${release_dir}"' in application_script
    assert application_script.index("set -e") < application_script.index("open-signage-post-update")
    assert application_script.index("open-signage-post-update") < application_script.index("set +e")
    assert application_script.index("set +e") < application_script.index("systemctl stop open-signage.service")
    assert "systemctl daemon-reload" in post_update
    assert "cec-utils locales wlr-randr wlopm wtype" in post_update
    assert '@@KIOSK_USER@@|${KIOSK_USER}' in post_update
    assert "open-signage-system-action setup_live" in post_update
    assert "set -euo pipefail" in post_update
    assert "cec-utils" in installer
    assert "open-signage-display-control.path" in installer
    assert "open-signage-display-schedule.timer" in installer
    assert "  wlopm" in installer
    display_helper = (PROJECT_ROOT / "deploy/open-signage-display-control").read_text(encoding="utf-8")
    assert "cec-client" in display_helper
    assert "wlopm" in display_helper
    assert "wlr-randr" in display_helper
    assert "vcgencmd" not in display_helper
    assert "@@KIOSK_USER@@" in display_helper
    assert "sudo" not in display_helper
