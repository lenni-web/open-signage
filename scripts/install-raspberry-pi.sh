#!/usr/bin/env bash
set -euo pipefail

readonly APP_USER="open-signage"
readonly APP_DIR="/opt/open-signage"
readonly DATA_DIR="/var/lib/open-signage"
readonly SERVICE_FILE="/etc/systemd/system/open-signage.service"
readonly KIOSK_COMMAND="/usr/local/bin/open-signage-kiosk"

PORT=8080
KIOSK_USER="signage"

usage() {
  printf '%s\n' \
    "Open Signage Raspberry-Pi-Installation" \
    "" \
    "Aufruf:" \
    "  sudo ./scripts/install-raspberry-pi.sh [--port PORT] [--kiosk-user BENUTZER]" \
    "" \
    "Optionen:" \
    "  --port PORT              HTTP-Port, Standard: 8080" \
    "  --kiosk-user BENUTZER    Kiosk-Benutzer, Standard: signage" \
    "  --help                   Diese Hilfe anzeigen"
}

fail() {
  printf 'Fehler: %s\n' "$1" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --port)
      (($# >= 2)) || fail "Nach --port fehlt ein Wert."
      PORT="$2"
      shift 2
      ;;
    --kiosk-user)
      (($# >= 2)) || fail "Nach --kiosk-user fehlt ein Wert."
      KIOSK_USER="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "Unbekannte Option: $1"
      ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || fail "Bitte mit sudo ausführen."
[[ "${PORT}" =~ ^[0-9]+$ ]] || fail "Der Port muss eine Zahl sein."
((PORT >= 1024 && PORT <= 65535)) || fail "Der Port muss zwischen 1024 und 65535 liegen."
[[ "${KIOSK_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "Ungültiger Kiosk-Benutzername."
command -v apt-get >/dev/null 2>&1 || fail "Dieses Skript benötigt Raspberry Pi OS."
[[ -f /etc/rpi-issue ]] || fail "Unterstützt wird Raspberry Pi OS Lite 64 Bit."
[[ "$(dpkg --print-architecture)" == "arm64" ]] || fail "Bitte Raspberry Pi OS Lite 64 Bit verwenden."

readonly PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

printf 'Installiere minimales Wayland-System und Chromium …\n'
apt-get update
apt-get install --no-install-recommends -y \
  chromium \
  curl \
  fonts-dejavu-core \
  fonts-liberation \
  python3 \
  python3-pip \
  python3-venv \
  rpd-wayland-core

command -v labwc >/dev/null 2>&1 || fail "labwc wurde nicht installiert."
command -v raspi-config >/dev/null 2>&1 || fail "raspi-config wurde nicht gefunden."

if ! id "${KIOSK_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${KIOSK_USER}"
fi
for group in audio video render input; do
  if getent group "${group}" >/dev/null; then
    usermod --append --groups "${group}" "${KIOSK_USER}"
  fi
done

readonly KIOSK_HOME="$(getent passwd "${KIOSK_USER}" | cut -d: -f6)"
[[ -n "${KIOSK_HOME}" ]] || fail "Home-Verzeichnis von ${KIOSK_USER} konnte nicht ermittelt werden."

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${DATA_DIR}" --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

printf 'Installiere Open Signage nach %s …\n' "${APP_DIR}"
install -d -o root -g root -m 0755 "${APP_DIR}"
cp -a "${PROJECT_DIR}/pyproject.toml" "${PROJECT_DIR}/README.md" "${APP_DIR}/"
cp -a "${PROJECT_DIR}/src" "${APP_DIR}/"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install "${APP_DIR}"

install -d -o "${APP_USER}" -g "${APP_USER}" -m 0750 "${DATA_DIR}"

sed "s/@@PORT@@/${PORT}/g" \
  "${PROJECT_DIR}/deploy/open-signage.service" >"${SERVICE_FILE}"
chmod 0644 "${SERVICE_FILE}"

sed \
  -e "s|@@PLAYER_URL@@|http://127.0.0.1:${PORT}/player|g" \
  -e "s|@@HEALTH_URL@@|http://127.0.0.1:${PORT}/api/health|g" \
  "${PROJECT_DIR}/deploy/open-signage-kiosk" >"${KIOSK_COMMAND}"
chmod 0755 "${KIOSK_COMMAND}"

readonly AUTOSTART_DIR="${KIOSK_HOME}/.config/labwc"
readonly AUTOSTART_FILE="${AUTOSTART_DIR}/autostart"
install -d -o "${KIOSK_USER}" -g "${KIOSK_USER}" -m 0755 "${AUTOSTART_DIR}"
touch "${AUTOSTART_FILE}"
if ! grep -qxF "${KIOSK_COMMAND} &" "${AUTOSTART_FILE}"; then
  printf '\n%s &\n' "${KIOSK_COMMAND}" >>"${AUTOSTART_FILE}"
fi
chown "${KIOSK_USER}:${KIOSK_USER}" "${AUTOSTART_FILE}"

printf 'Aktiviere Wayland, labwc und grafischen Autologin …\n'
SUDO_USER="${KIOSK_USER}" raspi-config nonint do_wayland W2
SUDO_USER="${KIOSK_USER}" raspi-config nonint do_boot_behaviour B4
systemctl set-default graphical.target
systemctl enable lightdm.service

systemctl daemon-reload
systemctl enable --now open-signage.service

"${PROJECT_DIR}/scripts/verify-installation.sh" --port "${PORT}"

printf '\nOpen Signage wurde installiert.\n'
printf 'Verwaltung: http://%s:%s/\n' "$(hostname -I | awk '{print $1}')" "${PORT}"
printf 'Player:     http://127.0.0.1:%s/player\n' "${PORT}"
printf 'Bitte jetzt neu starten: sudo reboot\n'
printf 'Danach öffnet %s den Player automatisch im Kioskmodus.\n' "${KIOSK_USER}"
