#!/usr/bin/env bash
# Erstellt ein Open-Signage-Release: Version erhöhen, Changelog datieren,
# Tests ausführen, Release-Commit und Tag anlegen und optional pushen.
set -euo pipefail

usage() {
  printf '%s\n' \
    "Open-Signage-Release erstellen" \
    "" \
    "Aufruf:" \
    "  scripts/release.sh VERSION [--push] [--trailer \"Schlüssel: Wert\"]" \
    "" \
    "Beispiel:" \
    "  scripts/release.sh 0.19.0 --push" \
    "" \
    "Optionen:" \
    "  --push               Release-Commit und Tag anschließend zu origin pushen" \
    "  --trailer TEXT       zusätzliche Zeile am Ende der Commit-Nachricht" \
    "  --help               Diese Hilfe anzeigen"
}

fail() {
  printf 'Fehler: %s\n' "$1" >&2
  exit 1
}

VERSION=""
PUSH=0
TRAILER=""
while (($#)); do
  case "$1" in
    --push) PUSH=1; shift ;;
    --trailer)
      (($# >= 2)) || fail "Nach --trailer fehlt ein Wert."
      TRAILER="$2"
      shift 2
      ;;
    --help|-h) usage; exit 0 ;;
    -*) fail "Unbekannte Option: $1" ;;
    *)
      [[ -z "${VERSION}" ]] || fail "Es darf nur eine Version angegeben werden."
      VERSION="$1"
      shift
      ;;
  esac
done

[[ -n "${VERSION}" ]] || { usage; exit 1; }
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Version muss MAJOR.MINOR.PATCH sein, z. B. 0.19.0."

cd "$(dirname "${BASH_SOURCE[0]}")/.."
readonly VERSION_FILE="src/open_signage/version.py"
readonly CHANGELOG="CHANGELOG.md"
readonly TAG="v${VERSION}"

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "${branch}" == "main" ]] || fail "Releases werden von main erstellt (aktuell: ${branch})."
[[ -z "$(git status --porcelain)" ]] || fail "Das Arbeitsverzeichnis enthält nicht committete Änderungen."
git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null && fail "Tag ${TAG} existiert bereits."

if [[ -x .venv/bin/python ]]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi

current="$("${PYTHON}" -c 'import re, pathlib; print(re.search(r"__version__ = \"(.+)\"", pathlib.Path("'"${VERSION_FILE}"'").read_text()).group(1))')"
highest="$(printf '%s\n%s\n' "${current}" "${VERSION}" | sort -V | tail -n1)"
[[ "${VERSION}" != "${current}" && "${highest}" == "${VERSION}" ]] || \
  fail "Neue Version ${VERSION} muss größer als die aktuelle Version ${current} sein."

# Unter „Unreleased“ muss etwas stehen, sonst gibt es nichts zu veröffentlichen.
unreleased="$(awk '/^## \[Unreleased\]/ { found = 1; next } found && /^## \[/ { exit } found { print }' "${CHANGELOG}")"
grep -q '[^[:space:]]' <<<"${unreleased}" || fail "Im Changelog steht unter „Unreleased“ nichts."

today="$(date +%F)"
printf 'Release %s → %s (%s)\n' "${current}" "${VERSION}" "${today}"
"${PYTHON}" - "${VERSION}" "${today}" "${VERSION_FILE}" "${CHANGELOG}" <<'PYTHON'
import pathlib, re, sys

version, today, version_file, changelog = sys.argv[1:]
path = pathlib.Path(version_file)
path.write_text(re.sub(r'__version__ = ".+"', f'__version__ = "{version}"', path.read_text()))
path = pathlib.Path(changelog)
text = path.read_text()
heading = "## [Unreleased]\n"
if text.count(heading) != 1:
    sys.exit("CHANGELOG.md muss genau einen Abschnitt „## [Unreleased]“ enthalten.")
path.write_text(text.replace(heading, f"{heading}\n## [{version}] – {today}\n", 1))
PYTHON

restore() {
  git checkout -- "${VERSION_FILE}" "${CHANGELOG}"
}

printf 'Führe Tests aus …\n'
if ! "${PYTHON}" -m pytest -q; then
  restore
  fail "Tests sind fehlgeschlagen; Version und Changelog wurden zurückgesetzt."
fi

message="Release ${TAG}"
[[ -z "${TRAILER}" ]] || message+=$'\n\n'"${TRAILER}"
git add "${VERSION_FILE}" "${CHANGELOG}"
git commit --quiet -m "${message}"
git tag -a "${TAG}" -m "Open Signage ${TAG}"
printf 'Release-Commit und Tag %s erstellt.\n' "${TAG}"

if ((PUSH)); then
  git push --atomic origin main "${TAG}"
  printf 'Gepusht. GitHub erstellt die Release-Seite automatisch.\n'
else
  printf 'Zum Veröffentlichen: git push --atomic origin main %s\n' "${TAG}"
fi
