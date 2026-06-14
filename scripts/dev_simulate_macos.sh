#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_ROOT="${ROOT_DIR}/.tmp-run/macos-sim"
PORT="${DECKSOUNDPAD_SIM_PORT:-8797}"
SESSION_FILE="${SIM_ROOT}/runtime/session.json"

mkdir -p "${SIM_ROOT}/settings" "${SIM_ROOT}/runtime" "${SIM_ROOT}/logs" "${SIM_ROOT}/home"
rm -f "${SESSION_FILE}"

export DECKSOUNDPAD_SIMULATE=1
export DECKY_PLUGIN_DIR="${ROOT_DIR}"
export DECKY_PLUGIN_SETTINGS_DIR="${SIM_ROOT}/settings"
export DECKY_PLUGIN_RUNTIME_DIR="${SIM_ROOT}/runtime"
export DECKY_PLUGIN_LOG_DIR="${SIM_ROOT}/logs"
export DECKY_USER_HOME="${SIM_ROOT}/home"
export PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}"

python3 "${ROOT_DIR}/scripts/generate_sample_sounds.py" >/dev/null
python3 - <<PY
from __future__ import annotations

import json
from pathlib import Path

config_path = Path("${SIM_ROOT}") / "settings" / "config.json"
config = {}
if config_path.exists():
    config = json.loads(config_path.read_text(encoding="utf-8"))
config.update(
    {
        "auth_enabled": False,
        "web_host": "127.0.0.1",
        "web_port": int("${PORT}"),
        "auto_port": True,
        "library_dirs": ["~/Music/DeckSoundpad"],
    }
)
config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "DeckSoundpad macOS simulation"
echo "  Requested port: ${PORT}"
echo "  Mode: DECKSOUNDPAD_SIMULATE=1"
echo "  Auth: disabled for local simulation"
echo

python3 -m decksoundpad.daemon --host 127.0.0.1 --port "${PORT}" &
DAEMON_PID="$!"

cleanup() {
    trap - INT TERM EXIT
    if kill -0 "${DAEMON_PID}" 2>/dev/null; then
        kill "${DAEMON_PID}" 2>/dev/null || true
        wait "${DAEMON_PID}" 2>/dev/null || true
    fi
}
trap cleanup INT TERM EXIT

python3 - "${SESSION_FILE}" "${DAEMON_PID}" <<'PY'
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

session_file = Path(sys.argv[1])
daemon_pid = int(sys.argv[2])
deadline = time.monotonic() + 8

while time.monotonic() < deadline:
    try:
        os.kill(daemon_pid, 0)
    except OSError:
        raise SystemExit("DeckSoundpad daemon exited before writing session.json")
    if session_file.exists():
        try:
            session = json.loads(session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            time.sleep(0.1)
            continue
        port = int(session.get("port") or 0)
        if port:
            print(f"  API:  http://127.0.0.1:{port}/healthz")
            print(f"  Web:  http://127.0.0.1:{port}/")
            print()
            break
    time.sleep(0.1)
else:
    raise SystemExit("Timed out waiting for DeckSoundpad session.json")
PY

wait "${DAEMON_PID}"
