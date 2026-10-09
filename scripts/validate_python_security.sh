#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BANDIT_BIN="${BANDIT_BIN:-bandit}"

if ! command -v "$BANDIT_BIN" >/dev/null 2>&1; then
  echo "Bandit is required. Install the pinned tooling with: python3 -m pip install -r requirements-security.txt" >&2
  exit 1
fi

EXPECTED_VERSION="$(sed -n 's/^bandit==//p' requirements-security.txt)"
ACTUAL_VERSION="$($BANDIT_BIN --version | awk 'NR == 1 { print $2 }')"
if [[ -z "$EXPECTED_VERSION" || "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]]; then
  echo "Bandit version mismatch: expected $EXPECTED_VERSION, got ${ACTUAL_VERSION:-unknown}" >&2
  exit 1
fi

"$BANDIT_BIN" -r main.py backend/decksoundpad -x backend/tests -ll
