#!/usr/bin/env bash
set -euo pipefail

PORT=8080

while (($#)); do
  case "$1" in
    --port)
      PORT="$2"
      shift 2
      ;;
    *)
      printf 'Unbekannte Option: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

[[ "${PORT}" =~ ^[0-9]+$ ]] || {
  printf 'Ungültiger Port: %s\n' "${PORT}" >&2
  exit 1
}

if command -v systemctl >/dev/null 2>&1; then
  systemctl is-active --quiet open-signage.service || {
    printf 'Open-Signage-Dienst ist nicht aktiv.\n' >&2
    systemctl status open-signage.service --no-pager >&2 || true
    exit 1
  }
  systemctl is-active --quiet open-signage-update.path || {
    printf 'Systemupdate-Überwachung ist nicht aktiv.\n' >&2
    exit 1
  }
fi

readonly BASE_URL="http://127.0.0.1:${PORT}"
for attempt in {1..20}; do
  if curl --fail --silent --show-error --max-time 2 "${BASE_URL}/api/health" >/dev/null; then
    break
  fi
  if ((attempt == 20)); then
    printf 'Server antwortet nicht unter %s.\n' "${BASE_URL}" >&2
    exit 1
  fi
  sleep 1
done

curl --fail --silent --show-error --max-time 5 --output /dev/null "${BASE_URL}/"
curl --fail --silent --show-error --max-time 5 --output /dev/null "${BASE_URL}/player"

printf 'Installation erfolgreich geprüft: %s\n' "${BASE_URL}"
