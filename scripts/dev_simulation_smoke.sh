#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_ROOT="${ROOT_DIR}/.tmp-run/macos-sim"
SESSION_FILE="${SIM_ROOT}/runtime/session.json"
LOG_FILE="${ROOT_DIR}/.tmp-run/macos-sim-smoke.log"

mkdir -p "${ROOT_DIR}/.tmp-run"
rm -f "${SESSION_FILE}" "${LOG_FILE}"

DECKSOUNDPAD_SIM_PORT="${DECKSOUNDPAD_SIM_PORT:-8797}" \
    "${ROOT_DIR}/scripts/dev_simulate_macos.sh" >"${LOG_FILE}" 2>&1 &
SIM_PID="$!"

cleanup() {
    trap - INT TERM EXIT
    if kill -0 "${SIM_PID}" 2>/dev/null; then
        kill "${SIM_PID}" 2>/dev/null || true
    fi
    python3 - "${SESSION_FILE}" <<'PY' 2>/dev/null || true
from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

session_file = Path(sys.argv[1])
if not session_file.exists():
    raise SystemExit(0)
try:
    session = json.loads(session_file.read_text(encoding="utf-8"))
    pid = int(session.get("pid") or 0)
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    raise SystemExit(0)
if pid:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
PY
    wait "${SIM_PID}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

PORT="$(
    python3 - "${SESSION_FILE}" "${SIM_PID}" <<'PY'
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

session_file = Path(sys.argv[1])
pid = int(sys.argv[2])
deadline = time.monotonic() + 10

while time.monotonic() < deadline:
    try:
        os.kill(pid, 0)
    except OSError:
        raise SystemExit("simulation daemon exited before session.json was available")
    if session_file.exists():
        try:
            session = json.loads(session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            time.sleep(0.1)
            continue
        port = int(session.get("port") or 0)
        if port:
            print(port)
            break
    time.sleep(0.1)
else:
    raise SystemExit("timed out waiting for simulation session.json")
PY
)"

BASE_URL="http://127.0.0.1:${PORT}"

curl -fsS "${BASE_URL}/healthz" >/dev/null
curl -fsSI "${BASE_URL}/" >/dev/null
curl -fsS "${BASE_URL}/api/v1/status/quick" >/dev/null
curl -fsS -X POST "${BASE_URL}/api/v1/sounds/refresh" >/tmp/decksoundpad-sounds.json

SOUND_ID="$(
    python3 - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

payload = json.loads(Path("/tmp/decksoundpad-sounds.json").read_text(encoding="utf-8"))
sounds = payload.get("sounds") or []
if not sounds:
    raise SystemExit("no sounds returned by simulation")
print(sounds[0]["id"])
PY
)"

curl -fsS \
    -H "Content-Type: application/json" \
    -d "{\"sound_id\":\"${SOUND_ID}\",\"volume\":0.5}" \
    "${BASE_URL}/api/v1/play" >/dev/null
curl -fsS -X POST "${BASE_URL}/api/v1/audio/repair" >/dev/null

python3 - "${BASE_URL}" <<'PY'
from __future__ import annotations

import json
import sys
import time
from urllib.request import urlopen

base_url = sys.argv[1]
deadline = time.monotonic() + 10
last_status = {}

while time.monotonic() < deadline:
    with urlopen(f"{base_url}/api/v1/status/quick", timeout=2) as response:
        last_status = json.loads(response.read().decode("utf-8"))
    audio = last_status.get("audio") or {}
    if audio.get("state") == "ready" and audio.get("sink_exists") and audio.get("virtual_mic_exists"):
        break
    time.sleep(0.3)
else:
    raise SystemExit(f"audio repair did not reach ready state: {last_status!r}")
PY

echo "DeckSoundpad simulation smoke passed at ${BASE_URL}"
