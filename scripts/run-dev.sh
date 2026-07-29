#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn --app-dir src open_signage.main:app --reload "$@"
