"""Version, Changelog, Installer, Updater und Systemvorlagen."""

import json
import subprocess
from pathlib import Path

import pytest

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

    installer = (PROJECT_ROOT / "scripts/install.sh").read_text(
        encoding="utf-8"
    )
    assert "rpd-wayland-core" in installer
    assert "raspi-config nonint do_boot_behaviour B4" in installer
    assert 'KIOSK_USER="signage"' in installer
    assert "ffmpeg" in installer
    assert "--mode MODUS" in installer
    assert "--controller-url URL" in installer
    assert "OPEN_SIGNAGE_MODE" in installer
    assert "  wtype" in installer
    # Systemintegration teilen sich Installer und Anwendungsupdater.
    post_update = (PROJECT_ROOT / "deploy/open-signage-post-update").read_text(encoding="utf-8")
    assert 'bash "${PROJECT_DIR}/deploy/open-signage-post-update" "${PROJECT_DIR}"' in installer
    assert 'chmod 0755 "${AUTOSTART_FILE}"' in post_update
    assert "kiosk.log" in post_update
    assert 's|@@KIOSK_USER@@|${KIOSK_USER}|g' in post_update
    assert "locale-gen de_DE.UTF-8" in post_update
    assert "open-signage-chromium-policy.json" in post_update
    assert "open-signage-cursor-guard" in post_update
    assert "open-signage-labwc-rc.xml" in post_update
    assert 's/@@PORT@@/${PORT}/g' in post_update

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
    installer = (PROJECT_ROOT / "scripts/install.sh").read_text(
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

    post_update = (PROJECT_ROOT / "deploy/open-signage-post-update").read_text(encoding="utf-8")
    assert "open-signage-update.path" in post_update
    assert "open-signage-system-update" in post_update
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
    assert "open-signage-application-update.path" in post_update
    assert "git -C" in application_script
    assert "systemctl stop open-signage.service" in application_script
    assert "Healthcheck fehlgeschlagen" in application_script
    assert "ExecStart=/usr/local/sbin/open-signage-application-update" in application_service
    assert "ExecStartPre=/bin/sleep 2" in application_service
    assert "PathExists=/var/lib/open-signage/application-update.request" in application_path
    assert 'bash "${release_dir}/deploy/open-signage-post-update" "${release_dir}"' in application_script
    assert application_script.index("set -e") < application_script.index("open-signage-post-update")
    assert application_script.index("open-signage-post-update") < application_script.index("set +e")
    assert application_script.index("set +e") < application_script.index("systemctl stop open-signage.service")
    assert "systemctl daemon-reload" in post_update
    assert "cec-utils grim locales wlr-randr wlopm wtype" in post_update
    assert '@@KIOSK_USER@@|${KIOSK_USER}' in post_update
    assert "open-signage-system-action setup_live" in post_update
    assert "set -euo pipefail" in post_update
    assert "cec-utils" in installer
    assert "open-signage-display-control.path" in post_update
    assert "open-signage-display-schedule.timer" in post_update
    assert "  wlopm" in installer
    # Jede Unit, die das Skript installiert, muss im Repository existieren.
    for unit in ("open-signage-update.service", "open-signage-update.path",
                 "open-signage-application-update.service", "open-signage-application-update.path",
                 "open-signage-system-action.service", "open-signage-system-action.path",
                 "open-signage-display-control.service", "open-signage-display-control.path",
                 "open-signage-display-schedule.service", "open-signage-display-schedule.timer"):
        assert unit in post_update
        assert (PROJECT_ROOT / "deploy" / unit).is_file()
    display_helper = (PROJECT_ROOT / "deploy/open-signage-display-control").read_text(encoding="utf-8")
    assert "cec-client" in display_helper
    assert "wlopm" in display_helper
    assert "wlr-randr" in display_helper
    assert "vcgencmd" not in display_helper
    assert "@@KIOSK_USER@@" in display_helper
    assert "sudo" not in display_helper


def test_release_tooling_checks_version_changelog_and_tests():
    release = (PROJECT_ROOT / "scripts/release.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in release
    assert '"${PYTHON}" -m pytest -q' in release
    assert "git tag -a" in release and "git push --atomic origin main" in release
    assert release.index("pytest") < release.index("git commit")
    ci = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in ci and "shellcheck" in ci and "ffmpeg" in ci
    release_workflow = (PROJECT_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "gh release create" in release_workflow and "CHANGELOG.md" in release_workflow



def test_updated_release_starts_and_rollback_restores_database():
    service = (PROJECT_ROOT / "deploy/open-signage.service").read_text(encoding="utf-8")
    exec_start = next(line for line in service.splitlines() if line.startswith("ExecStart="))
    # Konsolenskripte enthalten den Baupfad und funktionieren nach dem Verschieben nicht.
    assert exec_start.startswith("ExecStart=/opt/open-signage/.venv/bin/python -m uvicorn ")
    updater = (PROJECT_ROOT / "deploy/open-signage-application-update").read_text(encoding="utf-8")
    assert updater.index('cp -a "${DATA_DIR}"/open-signage.sqlite3*') < updater.index('mv "${APP_DIR}" "${backup_dir}"')
    assert 'cp -a "${database_backup}"/open-signage.sqlite3* "${DATA_DIR}/"' in updater
    assert "journalctl -u open-signage.service" in updater


WPCTL_STATUS = """Audio
 ├─ Sinks:
 │      35. Built-in Audio Digital Stereo (HDMI) [vol: 0.40]
 │  *   57. Built-in Audio Stereo               [vol: 0.40]
 │
 ├─ Sources:
 │
Video
 ├─ Sinks:
 ├─ Sources:
 │  *   76. bcm2835-isp (V4L2)
"""


GNU_SED = subprocess.run(["sed", "--version"], capture_output=True).returncode == 0


def script_section(path: str, start: str, end: str) -> str:
    text = (PROJECT_ROOT / path).read_text(encoding="utf-8")
    return text[text.index(start):text.index(end)]


@pytest.mark.parametrize(("config", "expected"), [
    ("dtoverlay=vc4-kms-v3d\ndtparam=audio=on\n", "dtoverlay=vc4-kms-v3d\ndtparam=audio=off\n"),
    ("dtoverlay=vc4-kms-v3d\n[cm5]\nfoo=1\n",
     "dtoverlay=vc4-kms-v3d\n[cm5]\nfoo=1\n\n[all]\n# Open Signage: Ton ausschließlich über HDMI\ndtparam=audio=off\n"),
    ("dtoverlay=vc4-kms-v3d\ndtparam=audio=off\n", "dtoverlay=vc4-kms-v3d\ndtparam=audio=off\n"),
    ("dtparam=audio=on\n", "dtparam=audio=on\n"),
])
def test_post_update_disables_analog_audio_only_with_kms(tmp_path: Path, config: str, expected: str):
    if "audio=on" in config and expected != config and not GNU_SED:
        pytest.skip("sed -i im Skript erfordert GNU sed wie auf dem Raspberry Pi")
    boot_config = tmp_path / "config.txt"
    boot_config.write_text(config, encoding="utf-8")
    section = script_section("deploy/open-signage-post-update", "BOOT_CONFIG=", "# --- Dienste aktivieren").rstrip()
    # Der Abschnitt liegt im Block für das Profil kiosk; dessen schließendes fi gehört nicht dazu.
    assert section.endswith("fi")
    section = section[:-2]
    section = section.replace("/boot/firmware/config.txt", str(boot_config)).replace("/boot/config.txt", str(boot_config))
    subprocess.run(["bash", "-euo", "pipefail", "-c", section], check=True, capture_output=True)
    assert boot_config.read_text(encoding="utf-8") == expected


def test_kiosk_switches_to_hdmi_and_sets_volume_once(tmp_path: Path):
    calls = tmp_path / "calls.log"
    fake = tmp_path / "bin" / "wpctl"
    fake.parent.mkdir()
    (tmp_path / "status.txt").write_text(WPCTL_STATUS, encoding="utf-8")
    fake.write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>"{calls}"
case "$1" in
  status) cat "{tmp_path / 'status.txt'}" ;;
  inspect) printf 'node.name = "alsa_output.platform-bcm2835_audio.stereo-fallback"\\n' ;;
esac
""", encoding="utf-8")
    fake.chmod(0o755)
    (tmp_path / "state" / "open-signage").mkdir(parents=True)
    function = script_section("deploy/open-signage-kiosk", "prepare_audio() {", "prepare_audio >/dev/null")
    script = f'XDG_STATE_HOME="{tmp_path / "state"}"\n{function}\nprepare_audio\nprepare_audio\n'
    subprocess.run(["bash", "-uo", "pipefail", "-c", script], check=True,
                   env={"PATH": f"{fake.parent}:/usr/bin:/bin"})
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert lines.count("set-default 35") == 2
    assert lines.count("set-volume 35 1.0") == 1 and lines.count("set-mute 35 0") == 1


def test_server_profile_installs_controller_without_kiosk():
    installer = (PROJECT_ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    wrapper = (PROJECT_ROOT / "scripts/install-raspberry-pi.sh").read_text(encoding="utf-8")
    assert 'install.sh" --profile kiosk "$@"' in wrapper
    server = installer[installer.index("  server)"):installer.index("  *)\n    fail \"Profil")]
    assert 'MODE="${MODE:-controller}"' in server and '"${ID:-}" == "debian"' in server
    assert "amd64|arm64" in server
    server_packages = installer[installer.index("printf 'Installiere Serverpakete"):installer.index("if ! id \"${APP_USER}\"")]
    assert "avahi-daemon" in server_packages and "chromium" not in server_packages
    assert "OPEN_SIGNAGE_PROFILE=%s" in installer and "PROFILE=%q" in installer
    assert 'PROFILE="${PROFILE}" PORT="${PORT}"' in installer

    post_update = (PROJECT_ROOT / "deploy/open-signage-post-update").read_text(encoding="utf-8")
    kiosk_units = post_update[post_update.index('if [[ "${PROFILE}" == "kiosk" ]]; then\n  sed "s|@@KIOSK_USER@@'):]
    assert "open-signage-display-control.path" in kiosk_units.split("fi\n")[0]
    common = post_update[post_update.index("UNITS=("):post_update.index('if [[ "${PROFILE}" == "kiosk" ]]; then\n  sed "s|@@KIOSK_USER@@')]
    assert "display" not in common
    assert post_update.index("# --- Kiosk") > post_update.index('if [[ "${PROFILE}" == "kiosk" ]]; then\n  # --- Kiosk') - 1

    updater = (PROJECT_ROOT / "deploy/open-signage-application-update").read_text(encoding="utf-8")
    assert 'PROFILE="${PROFILE:-kiosk}"' in updater and 'PROFILE="${PROFILE}" PORT="${PORT}"' in updater
    system_action = (PROJECT_ROOT / "deploy/open-signage-system-action").read_text(encoding="utf-8")
    assert "[amd64]=" in system_action and "[arm64]=" in system_action
    assert "mediamtx_${MEDIAMTX_VERSION}_linux_${arch}.tar.gz" in system_action


def _fake_system(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "root"
    calls = tmp_path / "calls.log"
    files = [
        "opt/open-signage/src/app.py", "var/lib/open-signage/open-signage.sqlite3",
        "var/lib/open-signage/media/bild.jpg", "usr/local/lib/open-signage/mediamtx",
        "usr/local/sbin/open-signage-system-action", "usr/local/bin/open-signage-kiosk",
        "etc/systemd/system/open-signage.service", "etc/systemd/system/open-signage-update.path",
        "etc/systemd/system/open-signage-mediamtx.service", "etc/systemd/system/andere.service",
        "etc/open-signage.env", "etc/chromium/policies/managed/open-signage.json",
        "home/signage/.config/labwc/rc.xml", "home/signage/.local/state/open-signage/kiosk.log",
        "usr/local/bin/anderes-programm",
    ]
    for name in files:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x", encoding="utf-8")
    (root / "etc/default").mkdir(parents=True)
    (root / "etc/default/open-signage-application-update").write_text(
        "SOURCE_REPOSITORY=/home/admin/open-signage\nSOURCE_USER=admin\nPORT=8080\nKIOSK_USER=signage\nPROFILE=kiosk\n",
        encoding="utf-8")
    (root / "home/signage/.config/labwc/autostart").write_text(
        "#!/bin/sh\neigenes-programm &\n/usr/local/bin/open-signage-cursor-guard &\n"
        "/usr/local/bin/open-signage-kiosk >>/home/signage/.local/state/open-signage/kiosk.log 2>&1 &\n",
        encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command, status in (("systemctl", 0), ("userdel", 0), ("id", 0), ("getent", 2)):
        stub = bin_dir / command
        stub.write_text(f'#!/bin/sh\necho "{command} $*" >> "{calls}"\nexit {status}\n', encoding="utf-8")
        stub.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "OPEN_SIGNAGE_UNINSTALL_ROOT": str(root)}
    return root, calls, env


def test_uninstall_removes_everything_and_keeps_foreign_files(tmp_path: Path):
    root, calls, env = _fake_system(tmp_path)
    aborted = subprocess.run(["bash", str(PROJECT_ROOT / "scripts/uninstall.sh")], env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert aborted.returncode != 0 and (root / "opt/open-signage").exists()

    result = subprocess.run(["bash", str(PROJECT_ROOT / "scripts/uninstall.sh"), "--yes"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    remaining = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
    assert remaining == ["etc/systemd/system/andere.service", "home/signage/.config/labwc/autostart",
                         "usr/local/bin/anderes-programm"]
    assert (root / "home/signage/.config/labwc/autostart").read_text(encoding="utf-8") == \
        "#!/bin/sh\neigenes-programm &\n"
    log = calls.read_text(encoding="utf-8")
    assert "systemctl disable --now open-signage.service" in log
    assert "systemctl disable --now open-signage-mediamtx.service" in log
    assert "userdel open-signage" in log
    assert "/home/admin/open-signage" in result.stdout


def test_uninstall_can_keep_data(tmp_path: Path):
    root, calls, env = _fake_system(tmp_path)
    result = subprocess.run(["bash", str(PROJECT_ROOT / "scripts/uninstall.sh"), "--yes", "--keep-data"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (root / "var/lib/open-signage/media/bild.jpg").exists()
    assert (root / "etc/open-signage.env").exists()
    assert not (root / "opt/open-signage").exists()
    assert "userdel" not in calls.read_text(encoding="utf-8")


def test_uninstall_knows_every_installed_unit():
    uninstall = (PROJECT_ROOT / "scripts/uninstall.sh").read_text(encoding="utf-8")
    units = uninstall[uninstall.index("readonly UNITS=("):uninstall.index(")\n", uninstall.index("readonly UNITS=("))]
    installed = {path.name for path in (PROJECT_ROOT / "deploy").iterdir()
                 if path.suffix in {".service", ".path", ".timer"}} | {"open-signage-mediamtx.service"}
    assert installed <= set(units.split())


def test_kiosk_installs_screenshot_helper():
    post_update = (PROJECT_ROOT / "deploy/open-signage-post-update").read_text(encoding="utf-8")
    kiosk = post_update[post_update.index('if [[ "${PROFILE}" == "kiosk" ]]; then\n  sed "s|@@KIOSK_USER@@'):]
    kiosk = kiosk[:kiosk.index("for unit in")]
    assert "/usr/local/sbin/open-signage-screenshot" in kiosk and "open-signage-screenshot.path)" in kiosk
    helper = (PROJECT_ROOT / "deploy/open-signage-screenshot").read_text(encoding="utf-8")
    assert '"-s", SCALE' in helper and 'KIOSK_USER = "@@KIOSK_USER@@"' in helper
    assert "PathExists=/var/lib/open-signage/screenshot-request" in \
        (PROJECT_ROOT / "deploy/open-signage-screenshot.path").read_text(encoding="utf-8")
    assert "grim" in (PROJECT_ROOT / "scripts/install.sh").read_text(encoding="utf-8")


def _load_screenshot_helper():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("screenshot_helper", str(PROJECT_ROOT / "deploy/open-signage-screenshot"))
    spec = importlib.util.spec_from_loader("screenshot_helper", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_screenshot_falls_back_to_png_when_grim_lacks_jpeg(tmp_path: Path, monkeypatch):
    # grim 1.4.0 aus Raspberry Pi OS: "jpeg support disabled", PNG funktioniert.
    grim = tmp_path / "grim"
    grim.write_text(
        "#!/bin/sh\n"
        'case "$*" in *"-t jpeg"*) echo "jpeg support disabled" >&2; exit 1;; esac\n'
        "printf '\\211PNG\\r\\n\\032\\nDATA'\n", encoding="utf-8")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\ncat >/dev/null\nprintf '\\377\\330\\377\\340JPEG'\n", encoding="utf-8")
    for tool in (grim, ffmpeg):
        tool.chmod(0o755)
    helper = _load_screenshot_helper()
    monkeypatch.setattr(helper.shutil, "which", lambda name: str(ffmpeg) if name == "ffmpeg" and ffmpeg.exists() else None)
    image, detail = helper.capture([str(grim)])
    assert image == b"\xff\xd8\xff\xe0JPEG" and detail == ""

    ffmpeg.unlink()
    assert helper.capture([str(grim)]) == (None, "ffmpeg fehlt für die Umwandlung nach JPEG.")
    grim.write_text("#!/bin/sh\necho 'compositor does not support screencopy' >&2\nexit 1\n", encoding="utf-8")
    assert helper.capture([str(grim)]) == (None, "compositor does not support screencopy")
