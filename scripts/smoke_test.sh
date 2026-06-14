#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${DECKSOUNDPAD_URL:-http://127.0.0.1:8787}"
AUTH_ARGS=()
if [[ -n "${DECKSOUNDPAD_TOKEN:-}" ]]; then
    AUTH_ARGS=(-H "Authorization: Bearer ${DECKSOUNDPAD_TOKEN}")
fi

curl -fsS "${BASE_URL}/healthz"
curl -fsSI "${BASE_URL}/" >/dev/null
curl -fsS "${AUTH_ARGS[@]}" "${BASE_URL}/api/v1/status"
curl -fsS "${AUTH_ARGS[@]}" "${BASE_URL}/api/v1/sounds"
