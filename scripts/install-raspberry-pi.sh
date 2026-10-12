#!/usr/bin/env bash
# Kurzform für Raspberry Pis mit Bildschirm; siehe scripts/install.sh.
set -euo pipefail

exec "$(dirname "${BASH_SOURCE[0]}")/install.sh" --profile kiosk "$@"
