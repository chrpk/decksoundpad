#!/usr/bin/env bash
set -euo pipefail

SINK_NAME="decksoundpad_sink"
MIC_NAME="decksoundpad_mic"
SINK_DESC="DeckSoundpad internal mix bus"
MIC_DESC="DeckSoundpad mic"
LOOPBACK_DESC="DeckSoundpad mic passthrough"
POC_TIMEOUT="${DECKSOUNDPAD_POC_TIMEOUT:-8}"

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2
}

have() {
  command -v "$1" >/dev/null 2>&1
}

run_timeout() {
  local seconds="$1"
  shift
  if have python3; then
    python3 - "$seconds" "$@" <<'PY'
from __future__ import annotations

import subprocess
import sys

timeout = float(sys.argv[1])
args = sys.argv[2:]
try:
    completed = subprocess.run(
        args,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
except subprocess.TimeoutExpired as exc:
    if exc.stdout:
        sys.stdout.write(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode())
    if exc.stderr:
        sys.stderr.write(exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode())
    sys.stderr.write(f"timeout after {timeout:.1f}s: {' '.join(args)}\n")
    raise SystemExit(124)

sys.stdout.write(completed.stdout)
sys.stderr.write(completed.stderr)
raise SystemExit(completed.returncode)
PY
  elif have timeout; then
    timeout "${seconds}" "$@"
  else
    "$@"
  fi
}

if ! have pactl; then
  log "pactl not found"
  exit 1
fi

modules="$(
  run_timeout "${POC_TIMEOUT}" pactl list modules short |
    grep -E "${SINK_NAME}|${MIC_NAME}|${SINK_DESC}|${MIC_DESC}|${LOOPBACK_DESC}|sink=${SINK_NAME}" || true
)"

module_ids="$(awk '{print $1}' <<<"${modules}" | sort -rn | sed '/^$/d')"
if [[ -z "${module_ids}" ]]; then
  log "no DeckSoundpad modules found"
  exit 0
fi

while read -r module_id; do
  [[ -n "${module_id}" ]] || continue
  log "unloading DeckSoundpad module ${module_id}"
  run_timeout "${POC_TIMEOUT}" pactl unload-module "${module_id}" || true
done <<<"${module_ids}"

log "remaining DeckSoundpad sources:"
run_timeout "${POC_TIMEOUT}" pactl list sources short | grep -E "${MIC_NAME}|${SINK_NAME}" || true
