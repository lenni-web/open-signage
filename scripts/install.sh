#!/usr/bin/env bash
# Installiert Open Signage.
#
# Profile:
# - kiosk:  Raspberry Pi mit Bildschirm (Raspberry Pi OS Lite 64 Bit), wahlweise
#           als Einzelgerät, Controller oder Display.
# - server: Rechner ohne Bildschirm (Debian 13, amd64 oder arm64) als zentraler
#           Controller für mehrere Displays.
set -euo pipefail

readonly APP_USER="open-signage"
readonly APP_DIR="/opt/open-signage"
readonly DATA_DIR="/var/lib/open-signage"
readonly APPLICATION_UPDATE_CONFIG="/etc/default/open-signage-application-update"
readonly APP_ENV_FILE="/etc/open-signage.env"

PROFILE="kiosk"
PORT=8080
KIOSK_USER="signage"
KIOSK_USER_SET=0
MODE=""
CONTROLLER_URL=""

usage() {
  printf '%s\n' \
    "Open Signage installieren" \
    "" \
    "Aufruf:" \
    "  sudo ./scripts/install.sh [--profile kiosk|server] [Optionen]" \
    "" \
    "Raspberry Pi mit Bildschirm (Standard):" \
    "  sudo ./scripts/install.sh --profile kiosk [--mode MODUS] [--controller-url URL] [--kiosk-user BENUTZER]" \
    "" \
    "Mini-PC als Controller ohne Bildschirm (Debian 13):" \
    "  sudo ./scripts/install.sh --profile server" \
    "" \
    "Optionen:" \
    "  --profile PROFIL         kiosk (Standard) oder server" \
    "  --port PORT              HTTP-Port, Standard: 8080" \
    "  --kiosk-user BENUTZER    Kiosk-Benutzer, Standard: signage (nur kiosk)" \
    "  --mode MODUS             standalone, controller oder display (nur kiosk)" \
    "  --controller-url URL     Controller-Adresse für den Display-Modus" \
    "  --help                   Diese Hilfe anzeigen"
}

fail() {
  printf 'Fehler: %s\n' "$1" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --profile)
      (($# >= 2)) || fail "Nach --profile fehlt ein Wert."
      PROFILE="$2"
      shift 2
      ;;
    --port)
      (($# >= 2)) || fail "Nach --port fehlt ein Wert."
      PORT="$2"
      shift 2
      ;;
    --kiosk-user)
      (($# >= 2)) || fail "Nach --kiosk-user fehlt ein Wert."
      KIOSK_USER="$2"
      KIOSK_USER_SET=1
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
command -v apt-get >/dev/null 2>&1 || fail "Dieses Skript benötigt ein Debian-basiertes System."
readonly ARCH="$(dpkg --print-architecture)"

case "${PROFILE}" in
  kiosk)
    MODE="${MODE:-standalone}"
    [[ "${KIOSK_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "Ungültiger Kiosk-Benutzername."
    [[ "${MODE}" =~ ^(standalone|controller|display)$ ]] || fail "Modus muss standalone, controller oder display sein."
    if [[ "${MODE}" == "display" ]]; then
      [[ "${CONTROLLER_URL}" =~ ^https?://[^[:space:]]+$ ]] || fail "Für display ist --controller-url mit http:// oder https:// erforderlich."
    fi
    [[ -f /etc/rpi-issue ]] || fail "Das Profil kiosk unterstützt Raspberry Pi OS Lite 64 Bit."
    [[ "${ARCH}" == "arm64" ]] || fail "Bitte Raspberry Pi OS Lite 64 Bit verwenden."
    ;;
  server)
    MODE="${MODE:-controller}"
    [[ "${MODE}" == "controller" ]] || fail "Das Profil server ist ein Controller ohne Bildschirm; --mode entfällt."
    [[ -z "${CONTROLLER_URL}" ]] || fail "--controller-url gilt nur für Displays."
    ((KIOSK_USER_SET == 0)) || fail "--kiosk-user gilt nur für das Profil kiosk."
    KIOSK_USER=""
    [[ "${ARCH}" =~ ^(amd64|arm64)$ ]] || fail "Unterstützt werden amd64 und arm64 (gefunden: ${ARCH})."
    # shellcheck source=/dev/null
    source /etc/os-release
    [[ "${ID:-}" == "debian" ]] || fail "Das Profil server unterstützt Debian (gefunden: ${PRETTY_NAME:-unbekannt})."
    [[ "${VERSION_ID:-}" == "13" ]] || \
      printf 'Hinweis: Getestet für Debian 13, gefunden: %s.\n' "${PRETTY_NAME:-unbekannt}"
    ;;
  *)
    fail "Profil muss kiosk oder server sein."
    ;;
esac

readonly PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SOURCE_USER="${SUDO_USER:-root}"
git -C "${PROJECT_DIR}" rev-parse --git-dir >/dev/null 2>&1 || \
  fail "Das Installationsverzeichnis muss ein Git-Repository sein."
id "${SOURCE_USER}" >/dev/null 2>&1 || fail "Quellbenutzer ${SOURCE_USER} existiert nicht."

apt-get update
if [[ "${PROFILE}" == "kiosk" ]]; then
  printf 'Installiere minimales Wayland-System und Chromium …\n'
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

  if ! id "${KIOSK_USER}" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "${KIOSK_USER}"
  fi
  for group in audio video render input; do
    if getent group "${group}" >/dev/null; then
      usermod --append --groups "${group}" "${KIOSK_USER}"
    fi
  done
else
  printf 'Installiere Serverpakete …\n'
  # avahi-daemon macht den Server im lokalen Netz als <hostname>.local erreichbar.
  apt-get install --no-install-recommends -y \
    avahi-daemon \
    ca-certificates \
    curl \
    ffmpeg \
    iproute2 \
    python3 \
    python3-pip \
    python3-venv
fi

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
fi
# Bei einer erneuten Installation die vorherigen Angaben ersetzen statt anhängen.
sed -i '/^OPEN_SIGNAGE_\(MODE\|CONTROLLER_URL\|PROFILE\)=/d' "${APP_ENV_FILE}"
printf 'OPEN_SIGNAGE_MODE=%s\nOPEN_SIGNAGE_CONTROLLER_URL=%s\nOPEN_SIGNAGE_PROFILE=%s\n' \
  "${MODE}" "${CONTROLLER_URL}" "${PROFILE}" >>"${APP_ENV_FILE}"
chmod 0600 "${APP_ENV_FILE}"

install -d -o root -g root -m 0755 /etc/default
printf 'SOURCE_REPOSITORY=%q\nSOURCE_USER=%q\nPORT=%q\nKIOSK_USER=%q\nPROFILE=%q\n' \
  "${PROJECT_DIR}" "${SOURCE_USER}" "${PORT}" "${KIOSK_USER}" "${PROFILE}" >"${APPLICATION_UPDATE_CONFIG}"
chmod 0600 "${APPLICATION_UPDATE_CONFIG}"

printf 'Richte Systemdienste und Live-Server ein …\n'
# Dasselbe Skript verwendet der Anwendungsupdater bei jedem Update.
PROFILE="${PROFILE}" PORT="${PORT}" KIOSK_USER="${KIOSK_USER}" \
  bash "${PROJECT_DIR}/deploy/open-signage-post-update" "${PROJECT_DIR}"

if [[ "${PROFILE}" == "kiosk" ]]; then
  printf 'Aktiviere Wayland, labwc und grafischen Autologin …\n'
  SUDO_USER="${KIOSK_USER}" raspi-config nonint do_wayland W2
  SUDO_USER="${KIOSK_USER}" raspi-config nonint do_boot_behaviour B4
  systemctl set-default graphical.target
  systemctl enable lightdm.service
fi

if [[ -n "${INITIAL_PASSWORD}" ]]; then
  printf '\nInitiales Verwaltungspasswort: %s\n' "${INITIAL_PASSWORD}"
  printf 'Bitte nach der ersten Anmeldung sofort unter Einstellungen ändern.\n'
fi
systemctl enable --now open-signage.service

"${PROJECT_DIR}/scripts/verify-installation.sh" --port "${PORT}"

readonly ADDRESS="$(hostname -I | awk '{print $1}')"
printf '\nOpen Signage wurde installiert.\n'
printf 'Profil:        %s\n' "${PROFILE}"
printf 'Betriebsmodus: %s\n' "${MODE}"
printf 'Verwaltung:    http://%s:%s/ (oder http://%s.local:%s/)\n' "${ADDRESS}" "${PORT}" "$(hostname)" "${PORT}"
if [[ "${PROFILE}" == "kiosk" ]]; then
  printf 'Player:        http://127.0.0.1:%s/player\n' "${PORT}"
  printf 'Bitte jetzt neu starten: sudo reboot\n'
  printf 'Danach öffnet %s den Player automatisch im Kioskmodus.\n' "${KIOSK_USER}"
else
  printf 'Displays koppeln: Pairing-Code unter Einstellungen → Controller-/Display-Synchronisierung.\n'
  printf 'Controller-Adresse für Displays: http://%s.local:%s\n' "$(hostname)" "${PORT}"
  printf 'OBS (WHIP):    http://%s:8889/live/whip\n' "${ADDRESS}"
fi
