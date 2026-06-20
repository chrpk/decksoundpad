#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PATTERN='-----BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{30,255}|github_pat_[A-Za-z0-9_]{20,}_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,}|npm_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{35}|sk-(proj-)?[A-Za-z0-9_-]{32,}|sk_live_[A-Za-z0-9]{24,}|rk_live_[A-Za-z0-9]{24,}'
FOUND=0

echo "Scanning current tracked and untracked source files for high-confidence secret patterns..."
CURRENT_FILES=()
while IFS= read -r -d '' file; do
  CURRENT_FILES+=("$file")
done < <(git ls-files -z --cached --others --exclude-standard)

set +e
if [[ "${#CURRENT_FILES[@]}" -gt 0 ]]; then
  CURRENT_OUTPUT="$(grep -nEI -e "$PATTERN" -- "${CURRENT_FILES[@]}")"
  CURRENT_STATUS="$?"
else
  CURRENT_OUTPUT=""
  CURRENT_STATUS=1
fi
set -e
if [[ "$CURRENT_STATUS" -eq 0 ]]; then
  printf '%s\n' "$CURRENT_OUTPUT"
  FOUND=1
elif [[ "$CURRENT_STATUS" -ne 1 ]]; then
  echo "current-file secret scan failed" >&2
  exit "$CURRENT_STATUS"
fi

echo "Scanning git history patches for high-confidence secret patterns..."
set +e
HISTORY_OUTPUT="$(git log --all -p -- . | grep -nE -e "$PATTERN")"
HISTORY_STATUS="$?"
set -e
if [[ "$HISTORY_STATUS" -eq 0 ]]; then
  printf '%s\n' "$HISTORY_OUTPUT"
  FOUND=1
elif [[ "$HISTORY_STATUS" -ne 1 ]]; then
  echo "git history secret scan failed" >&2
  exit "$HISTORY_STATUS"
fi

if [[ "$FOUND" -ne 0 ]]; then
  echo "Potential secret material found. Review output before publication." >&2
  exit 1
fi

echo "Basic secret scan passed."
