#!/usr/bin/env bash
set -euo pipefail

readonly APP_USER="open-signage"
readonly APP_DIR="/opt/open-signage"
readonly DATA_DIR="/var/lib/open-signage"
readonly SERVICE_FILE="/etc/systemd/system/open-signage.service"
readonly KIOSK_COMMAND="/usr/local/bin/open-signage-kiosk"
readonly UPDATE_COMMAND="/usr/local/sbin/open-signage-system-update"
readonly APPLICATION_UPDATE_COMMAND="/usr/local/sbin/open-signage-application-update"
readonly APPLICATION_UPDATE_CONFIG="/etc/default/open-signage-application-update"
readonly SYSTEM_ACTION_COMMAND="/usr/local/sbin/open-signage-system-action"
readonly DISPLAY_CONTROL_COMMAND="/usr/local/sbin/open-signage-display-control"
readonly APP_ENV_FILE="/etc/open-signage.env"

PORT=8080
KIOSK_USER="signage"
MODE="standalone"
CONTROLLER_URL=""

usage() {
  printf '%s\n' \
    "Open Signage Raspberry-Pi-Installation" \
    "" \
    "Aufruf:" \
    "  sudo ./scripts/install-raspberry-pi.sh [--mode MODUS] [--controller-url URL] [--port PORT] [--kiosk-user BENUTZER]" \
    "" \
    "Optionen:" \
    "  --port PORT              HTTP-Port, Standard: 8080" \
    "  --kiosk-user BENUTZER    Kiosk-Benutzer, Standard: signage" \
    "  --mode MODUS             standalone, controller oder display" \
    "  --controller-url URL     Controller-Adresse für den Display-Modus" \
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
    --mode)
      (($# >= 2)) || fail "Nach --mode fehlt ein Wert."
      MODE="$2"
      shift 2
      ;;
    --controller-url)
      (($# >= 2)) || fail "Nach --controller-url fehlt ein Wert."
      CONTROLLER_URL="$2"
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
[[ "${MODE}" =~ ^(standalone|controller|display)$ ]] || fail "Modus muss standalone, controller oder display sein."
if [[ "${MODE}" == "display" ]]; then
  [[ "${CONTROLLER_URL}" =~ ^https?://[^[:space:]]+$ ]] || fail "Für display ist --controller-url mit http:// oder https:// erforderlich."
fi
command -v apt-get >/dev/null 2>&1 || fail "Dieses Skript benötigt Raspberry Pi OS."
[[ -f /etc/rpi-issue ]] || fail "Unterstützt wird Raspberry Pi OS Lite 64 Bit."
[[ "$(dpkg --print-architecture)" == "arm64" ]] || fail "Bitte Raspberry Pi OS Lite 64 Bit verwenden."

readonly PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SOURCE_USER="${SUDO_USER:-root}"
git -C "${PROJECT_DIR}" rev-parse --git-dir >/dev/null 2>&1 || \
  fail "Das Installationsverzeichnis muss ein Git-Repository sein."
id "${SOURCE_USER}" >/dev/null 2>&1 || fail "Quellbenutzer ${SOURCE_USER} existiert nicht."

printf 'Installiere minimales Wayland-System und Chromium …\n'
apt-get update
apt-get install --no-install-recommends -y \
  chromium \
  cec-utils \
  curl \
  ffmpeg \
  fonts-dejavu-core \
  fonts-liberation \
  iw \
  locales \
  python3 \
  python3-pip \
  python3-venv \
  rpd-wayland-core \
  wlr-randr \
  wlopm \
  wtype

command -v labwc >/dev/null 2>&1 || fail "labwc wurde nicht installiert."
command -v raspi-config >/dev/null 2>&1 || fail "raspi-config wurde nicht gefunden."
if ! locale -a | grep -qi '^de_DE\.utf8$'; then
  sed -i 's/^# *\(de_DE.UTF-8 UTF-8\)/\1/' /etc/locale.gen
  locale-gen de_DE.UTF-8
fi

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

INITIAL_PASSWORD=""
if [[ ! -f "${APP_ENV_FILE}" ]]; then
  INITIAL_PASSWORD="$("${APP_DIR}/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(18))')"
  printf 'OPEN_SIGNAGE_INITIAL_PASSWORD=%s\nOPEN_SIGNAGE_MAX_UPLOAD_BYTES=%s\n' \
    "${INITIAL_PASSWORD}" "1073741824" >"${APP_ENV_FILE}"
  chmod 0600 "${APP_ENV_FILE}"
fi
printf 'OPEN_SIGNAGE_MODE=%s\nOPEN_SIGNAGE_CONTROLLER_URL=%s\n' \
  "${MODE}" "${CONTROLLER_URL}" >>"${APP_ENV_FILE}"
chmod 0600 "${APP_ENV_FILE}"

sed "s/@@PORT@@/${PORT}/g" \
  "${PROJECT_DIR}/deploy/open-signage.service" >"${SERVICE_FILE}"
chmod 0644 "${SERVICE_FILE}"

sed \
  -e "s|@@PLAYER_URL@@|http://127.0.0.1:${PORT}/player|g" \
  -e "s|@@HEALTH_URL@@|http://127.0.0.1:${PORT}/api/health|g" \
  "${PROJECT_DIR}/deploy/open-signage-kiosk" >"${KIOSK_COMMAND}"
chmod 0755 "${KIOSK_COMMAND}"
install -o root -g root -m 0755 \
  "${PROJECT_DIR}/deploy/open-signage-cursor-guard" \
  /usr/local/bin/open-signage-cursor-guard
install -d -o root -g root -m 0755 /etc/chromium/policies/managed
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-chromium-policy.json" \
  /etc/chromium/policies/managed/open-signage.json

install -o root -g root -m 0755 \
  "${PROJECT_DIR}/deploy/open-signage-system-update" "${UPDATE_COMMAND}"
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-update.service" \
  "/etc/systemd/system/open-signage-update.service"
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-update.path" \
  "/etc/systemd/system/open-signage-update.path"
install -o root -g root -m 0755 \
  "${PROJECT_DIR}/deploy/open-signage-application-update" "${APPLICATION_UPDATE_COMMAND}"
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-application-update.service" \
  "/etc/systemd/system/open-signage-application-update.service"
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-application-update.path" \
  "/etc/systemd/system/open-signage-application-update.path"
install -d -o root -g root -m 0755 /etc/default
printf 'SOURCE_REPOSITORY=%q\nSOURCE_USER=%q\nPORT=%q\nKIOSK_USER=%q\n' \
  "${PROJECT_DIR}" "${SOURCE_USER}" "${PORT}" "${KIOSK_USER}" >"${APPLICATION_UPDATE_CONFIG}"
chmod 0600 "${APPLICATION_UPDATE_CONFIG}"
install -o root -g root -m 0755 \
  "${PROJECT_DIR}/deploy/open-signage-system-action" "${SYSTEM_ACTION_COMMAND}"
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-system-action.service" "/etc/systemd/system/open-signage-system-action.service"
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-system-action.path" "/etc/systemd/system/open-signage-system-action.path"
sed "s|@@KIOSK_USER@@|${KIOSK_USER}|g" \
  "${PROJECT_DIR}/deploy/open-signage-display-control" >"${DISPLAY_CONTROL_COMMAND}"
chmod 0755 "${DISPLAY_CONTROL_COMMAND}"
for unit in open-signage-display-control.service open-signage-display-control.path \
  open-signage-display-schedule.service open-signage-display-schedule.timer; do
  install -o root -g root -m 0644 "${PROJECT_DIR}/deploy/${unit}" "/etc/systemd/system/${unit}"
done

readonly AUTOSTART_DIR="${KIOSK_HOME}/.config/labwc"
readonly AUTOSTART_FILE="${AUTOSTART_DIR}/autostart"
install -d -o "${KIOSK_USER}" -g "${KIOSK_USER}" -m 0755 "${AUTOSTART_DIR}"
install -o "${KIOSK_USER}" -g "${KIOSK_USER}" -m 0644 \
  "${PROJECT_DIR}/deploy/open-signage-labwc-rc.xml" "${AUTOSTART_DIR}/rc.xml"
install -d -o "${KIOSK_USER}" -g "${KIOSK_USER}" -m 0755 "${KIOSK_HOME}/.local/state/open-signage"
touch "${AUTOSTART_FILE}"
grep -q '^#!/bin/sh' "${AUTOSTART_FILE}" || sed -i '1i #!/bin/sh' "${AUTOSTART_FILE}"
sed -i '\|^/usr/local/bin/open-signage-kiosk|d' "${AUTOSTART_FILE}"
sed -i '\|^/usr/local/bin/open-signage-cursor-guard|d' "${AUTOSTART_FILE}"
printf '/usr/local/bin/open-signage-cursor-guard &\n' >>"${AUTOSTART_FILE}"
printf '%s >>%s 2>&1 &\n' "${KIOSK_COMMAND}" \
  "${KIOSK_HOME}/.local/state/open-signage/kiosk.log" >>"${AUTOSTART_FILE}"
chown "${KIOSK_USER}:${KIOSK_USER}" "${AUTOSTART_FILE}"
chmod 0755 "${AUTOSTART_FILE}"

printf 'Aktiviere Wayland, labwc und grafischen Autologin …\n'
SUDO_USER="${KIOSK_USER}" raspi-config nonint do_wayland W2
SUDO_USER="${KIOSK_USER}" raspi-config nonint do_boot_behaviour B4
systemctl set-default graphical.target
systemctl enable lightdm.service

systemctl daemon-reload
systemctl enable --now open-signage-update.path
systemctl enable --now open-signage-application-update.path
systemctl enable --now open-signage-system-action.path
systemctl enable --now open-signage-display-control.path
systemctl enable --now open-signage-display-schedule.timer

if [[ -n "${INITIAL_PASSWORD}" ]]; then
  printf '\nInitiales Verwaltungspasswort: %s\n' "${INITIAL_PASSWORD}"
  printf 'Bitte nach der ersten Anmeldung sofort auf der Systemseite ändern.\n'
fi
systemctl enable --now open-signage.service

"${PROJECT_DIR}/scripts/verify-installation.sh" --port "${PORT}"

printf '\nOpen Signage wurde installiert.\n'
printf 'Betriebsmodus: %s\n' "${MODE}"
printf 'Verwaltung: http://%s:%s/\n' "$(hostname -I | awk '{print $1}')" "${PORT}"
printf 'Player:     http://127.0.0.1:%s/player\n' "${PORT}"
printf 'Bitte jetzt neu starten: sudo reboot\n'
printf 'Danach öffnet %s den Player automatisch im Kioskmodus.\n' "${KIOSK_USER}"
