#!/usr/bin/env bash
# Entfernt Open Signage vollständig von diesem Gerät, etwa vor einer Neuinstallation.
#
# Systempakete (Python, ffmpeg, Chromium, Avahi …), der Kioskbenutzer mit seinem
# Autologin und die HDMI-Toneinstellung bleiben erhalten; eine erneute
# Installation verwendet sie wieder.
set -euo pipefail

# Nur für Tests: alle Pfade unterhalb dieses Verzeichnisses statt unter /.
readonly ROOT="${OPEN_SIGNAGE_UNINSTALL_ROOT:-}"
readonly APP_USER="open-signage"
readonly APP_DIR="${ROOT}/opt/open-signage"
readonly DATA_DIR="${ROOT}/var/lib/open-signage"
readonly MEDIAMTX_DIR="${ROOT}/usr/local/lib/open-signage"
readonly SYSTEMD_DIR="${ROOT}/etc/systemd/system"
readonly APPLICATION_UPDATE_CONFIG="${ROOT}/etc/default/open-signage-application-update"
readonly APP_ENV_FILE="${ROOT}/etc/open-signage.env"
readonly CHROMIUM_POLICY="${ROOT}/etc/chromium/policies/managed/open-signage.json"
readonly UNITS=(
  open-signage.service open-signage-mediamtx.service
  open-signage-update.service open-signage-update.path
  open-signage-application-update.service open-signage-application-update.path
  open-signage-system-action.service open-signage-system-action.path
  open-signage-display-control.service open-signage-display-control.path
  open-signage-display-schedule.service open-signage-display-schedule.timer
)

KEEP_DATA=0
ASSUME_YES=0

usage() {
  printf '%s\n' \
    "Open Signage entfernen" \
    "" \
    "Aufruf:" \
    "  sudo ./scripts/uninstall.sh [--keep-data] [--yes]" \
    "" \
    "Optionen:" \
    "  --keep-data   Inhalte, Medien, Backups und Zugangsdaten unter" \
    "                /var/lib/open-signage und /etc/open-signage.env behalten;" \
    "                eine spätere Installation übernimmt sie wieder." \
    "  --yes         Ohne Sicherheitsabfrage entfernen" \
    "  --help        Diese Hilfe anzeigen"
}

fail() {
  printf 'Fehler: %s\n' "$1" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --keep-data) KEEP_DATA=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) fail "Unbekannte Option: $1" ;;
  esac
done

[[ "${EUID}" -eq 0 || -n "${ROOT}" ]] || fail "Bitte mit sudo ausführen."

config_value() {
  [[ -f "${APPLICATION_UPDATE_CONFIG}" ]] || return 0
  sed -n "s/^$1=//p" "${APPLICATION_UPDATE_CONFIG}" | tail -n1
}

KIOSK_USER="$(config_value KIOSK_USER)"
KIOSK_USER="${KIOSK_USER:-signage}"
[[ "${KIOSK_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || KIOSK_USER="signage"
SOURCE_REPOSITORY="$(config_value SOURCE_REPOSITORY)"
KIOSK_HOME="$(getent passwd "${KIOSK_USER}" 2>/dev/null | cut -d: -f6 || true)"
KIOSK_HOME="${ROOT}${KIOSK_HOME:-/home/${KIOSK_USER}}"

printf 'Open Signage wird von diesem Gerät entfernt:\n'
printf '  - Dienste, Hilfsskripte und Live-Server (MediaMTX)\n'
printf '  - Programmdateien unter /opt/open-signage\n'
printf '  - Kiosk-Autostart von %s\n' "${KIOSK_USER}"
if ((KEEP_DATA)); then
  printf 'Erhalten bleiben Inhalte, Medien, Backups und Zugangsdaten (/var/lib/open-signage).\n'
else
  printf '  - ALLE Inhalte, Medien, Backups und Einstellungen unter /var/lib/open-signage\n'
  printf '\nWer Daten behalten will, lädt vorher unter Einstellungen → Backup ein Backup\n'
  printf 'mit Medien auf einen anderen Rechner herunter oder verwendet --keep-data.\n'
fi

if ! ((ASSUME_YES)); then
  [[ -t 0 ]] || fail "Ohne Terminal bitte --yes angeben."
  printf '\nZum Bestätigen ENTFERNEN eingeben: '
  read -r answer
  [[ "${answer}" == "ENTFERNEN" ]] || fail "Abgebrochen, es wurde nichts entfernt."
fi

printf 'Stoppe Dienste …\n'
for unit in "${UNITS[@]}"; do
  systemctl disable --now "${unit}" >/dev/null 2>&1 || true
done
for unit in "${UNITS[@]}"; do
  rm -f "${SYSTEMD_DIR}/${unit}"
done
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl reset-failed >/dev/null 2>&1 || true

printf 'Entferne Programmdateien …\n'
rm -rf "${APP_DIR}" "${MEDIAMTX_DIR}"
rm -f "${ROOT}"/usr/local/sbin/open-signage-* "${ROOT}"/usr/local/bin/open-signage-*
rm -f "${APPLICATION_UPDATE_CONFIG}" "${CHROMIUM_POLICY}"

AUTOSTART_FILE="${KIOSK_HOME}/.config/labwc/autostart"
if [[ -f "${AUTOSTART_FILE}" ]]; then
  printf 'Entferne Kiosk-Autostart …\n'
  remaining="$(grep -v -e '^/usr/local/bin/open-signage-kiosk' -e '^/usr/local/bin/open-signage-cursor-guard' \
    "${AUTOSTART_FILE}" || true)"
  printf '%s\n' "${remaining}" >"${AUTOSTART_FILE}"
  rm -f "${KIOSK_HOME}/.config/labwc/rc.xml"
fi
rm -rf "${KIOSK_HOME}/.local/state/open-signage"

if ((KEEP_DATA)); then
  printf 'Daten bleiben unter /var/lib/open-signage erhalten.\n'
else
  printf 'Entferne Daten …\n'
  rm -rf "${DATA_DIR}"
  rm -f "${APP_ENV_FILE}"
  if id "${APP_USER}" >/dev/null 2>&1; then
    userdel "${APP_USER}" >/dev/null 2>&1 || printf 'Hinweis: Benutzer %s konnte nicht entfernt werden.\n' "${APP_USER}"
  fi
fi

printf '\nOpen Signage wurde entfernt.\n'
if [[ -n "${SOURCE_REPOSITORY}" ]]; then
  printf 'Der Quellcode-Klon unter %s blieb erhalten; für eine frische Kopie:\n' "${SOURCE_REPOSITORY}"
  printf '  rm -rf %q && git clone https://github.com/lenni-web/open-signage.git\n' "${SOURCE_REPOSITORY}"
fi
printf 'Neu installieren: sudo ./scripts/install.sh --profile server  (Mini-PC)\n'
printf '              bzw. sudo ./scripts/install-raspberry-pi.sh      (Raspberry Pi)\n'
