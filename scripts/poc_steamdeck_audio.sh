#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SINK_NAME="decksoundpad_sink"
MIC_NAME="decksoundpad_mic"
SINK_DESC="DeckSoundpad internal mix bus"
MIC_DESC="DeckSoundpad mic"
LOOPBACK_DESC="DeckSoundpad mic passthrough"

POC_TIMEOUT="${DECKSOUNDPAD_POC_TIMEOUT:-8}"
LOG_DIR="${DECKSOUNDPAD_POC_LOG_DIR:-${ROOT_DIR}/.tmp-run/poc}"
LOG_FILE="${LOG_DIR}/steamdeck-audio-poc.log"
SAMPLE_FILE="${1:-${ROOT_DIR}/defaults/sounds/sample/ready-chime.wav}"
SKIP_PLAY="${DECKSOUNDPAD_POC_SKIP_PLAY:-0}"

mkdir -p "${LOG_DIR}"
: >"${LOG_FILE}"

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "${LOG_FILE}" >&2
}

have() {
  command -v "$1" >/dev/null 2>&1
}

need() {
  if ! have "$1"; then
    log "missing required command: $1"
    exit 1
  fi
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
    log "warning: neither python3 nor timeout found; running without timeout: $*"
    "$@"
  fi
}

capture_cmd() {
  log "+ $*"
  local output rc
  set +e
  output="$(run_timeout "${POC_TIMEOUT}" "$@" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "${output}" >>"${LOG_FILE}"
  if [[ ${rc} -ne 0 ]]; then
    log "command failed rc=${rc}: $*"
    [[ -n "${output}" ]] && log "${output}"
    return "${rc}"
  fi
  printf '%s\n' "${output}"
}

is_truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

is_real_source() {
  local source_name="$1"
  [[ -n "${source_name}" ]] || return 1
  [[ "${source_name}" != "${MIC_NAME}" ]] || return 1
  [[ "${source_name}" != "${SINK_NAME}.monitor" ]] || return 1
  [[ "${source_name}" != *.monitor ]] || return 1
  return 0
}

first_real_source() {
  local sources="$1"
  local index name rest
  while read -r index name rest; do
    if is_real_source "${name:-}"; then
      printf '%s\n' "${name}"
      return 0
    fi
  done <<<"${sources}"
  return 1
}

module_exists() {
  local modules="$1"
  shift
  local text="${modules}"
  local needle
  for needle in "$@"; do
    grep -Fq "${needle}" <<<"${text}" || return 1
  done
  return 0
}

source_exists_in() {
  local sources="$1"
  local source_name="$2"
  grep -Eq "^[0-9]+[[:space:]]+${source_name}[[:space:]]" <<<"${sources}"
}

load_module() {
  local module_name="$1"
  shift
  LOADED_MODULE_ID="$(capture_cmd pactl load-module "${module_name}" "$@" | tr -d '[:space:]')"
  log "loaded ${module_name} id=${LOADED_MODULE_ID:-unknown}"
}

unload_loaded_module() {
  if [[ -n "${LOADED_MODULE_ID:-}" && "${LOADED_MODULE_ID}" =~ ^[0-9]+$ ]]; then
    capture_cmd pactl unload-module "${LOADED_MODULE_ID}" >/dev/null || true
  fi
}

show_virtual_mic_diagnostics() {
  log "diagnostics: pactl info"
  capture_cmd pactl info || true
  log "diagnostics: pactl list sources short"
  capture_cmd pactl list sources short || true
  log "diagnostics: DeckSoundpad modules"
  capture_cmd pactl list modules short | grep -E "${SINK_NAME}|${MIC_NAME}|DeckSoundpad|module-remap-source|module-virtual-source" | tee -a "${LOG_FILE}" || true
}

ensure_virtual_mic() {
  local sources
  sources="$(capture_cmd pactl list sources short)"
  if source_exists_in "${sources}" "${MIC_NAME}"; then
    log "virtual mic already exists: ${MIC_NAME}"
    return 0
  fi

  log "creating virtual mic through module-virtual-source"
  load_module module-virtual-source \
    "master=${SINK_NAME}.monitor" \
    "source_name=${MIC_NAME}" \
    "source_properties=device.description=${MIC_DESC}"

  sources="$(capture_cmd pactl list sources short)"
  if source_exists_in "${sources}" "${MIC_NAME}"; then
    log "virtual mic created: ${MIC_NAME}"
    return 0
  fi

  log "module-virtual-source loaded but ${MIC_NAME} is not visible as a source; trying module-remap-source fallback"
  unload_loaded_module
  load_module module-remap-source \
    "master=${SINK_NAME}.monitor" \
    "source_name=${MIC_NAME}" \
    "source_properties=device.description=${MIC_DESC}"

  sources="$(capture_cmd pactl list sources short)"
  if source_exists_in "${sources}" "${MIC_NAME}"; then
    log "virtual mic created through module-remap-source: ${MIC_NAME}"
    return 0
  fi

  log "failed to create visible virtual input source: ${MIC_NAME}"
  show_virtual_mic_diagnostics
  exit 2
}

play_sample_to_virtual_mic() {
  local sample_name="decksoundpad_poc_$$_$(date +%s)"
  if [[ "${SAMPLE_FILE}" == *.wav || "${SAMPLE_FILE}" == *.WAV ]]; then
    capture_cmd pactl upload-sample "${SAMPLE_FILE}" "${sample_name}" >/dev/null
    capture_cmd pactl play-sample "${sample_name}" "${SINK_NAME}" >/dev/null
    sleep 1
    capture_cmd pactl remove-sample "${sample_name}" >/dev/null || true
    return
  fi
  if have pw-play; then
    capture_cmd pw-play "--target=${SINK_NAME}" "${SAMPLE_FILE}"
    return
  fi
  if have mpv; then
    capture_cmd mpv --no-video --really-quiet --ao=pulse "--audio-device=pulse/${SINK_NAME}" "${SAMPLE_FILE}"
    return
  fi
  log "no playback command found: install/use pw-play or mpv to play the sample"
  return 1
}

need pactl

if [[ ! -f "${SAMPLE_FILE}" ]]; then
  log "sample file not found: ${SAMPLE_FILE}"
  exit 1
fi

log "DeckSoundpad Steam Deck audio PoC"
log "log file: ${LOG_FILE}"
log "sample: ${SAMPLE_FILE}"
log "timeout per audio command: ${POC_TIMEOUT}s"
log "pactl: $(command -v pactl)"
log "pw-play: $(command -v pw-play || true)"
log "mpv: $(command -v mpv || true)"
log "ffmpeg: $(command -v ffmpeg || true)"

capture_cmd pactl info >/dev/null

sinks="$(capture_cmd pactl list sinks short)"
if grep -Eq "^[0-9]+[[:space:]]+${SINK_NAME}[[:space:]]" <<<"${sinks}"; then
  log "sink already exists: ${SINK_NAME}"
else
  load_module module-null-sink \
    "sink_name=${SINK_NAME}" \
    "sink_properties=device.description=${SINK_DESC}"
fi

sources="$(capture_cmd pactl list sources short)"
ensure_virtual_mic

sources="$(capture_cmd pactl list sources short)"
default_source="$(capture_cmd pactl get-default-source | tr -d '\r\n' || true)"
if is_real_source "${default_source}"; then
  real_source="${default_source}"
else
  real_source="$(first_real_source "${sources}" || true)"
fi

modules="$(capture_cmd pactl list modules short)"
if [[ -n "${real_source:-}" ]]; then
  log "selected real mic source: ${real_source}"
  if module_exists "${modules}" "module-loopback" "source=${real_source}" "sink=${SINK_NAME}"; then
    log "loopback already exists: ${real_source} -> ${SINK_NAME}"
  else
    load_module module-loopback \
      "source=${real_source}" \
      "sink=${SINK_NAME}" \
      "latency_msec=20" \
      "source_output_properties=media.name=${LOOPBACK_DESC}"
  fi
else
  log "no real mic source found; virtual mic will be soundboard-only"
fi

capture_cmd pactl set-default-source "${MIC_NAME}" >/dev/null
log "set default input source to ${MIC_NAME}"

log "current DeckSoundpad sources:"
capture_cmd pactl list sources short | grep -E "${MIC_NAME}|${SINK_NAME}|alsa_input|bluez_input" | tee -a "${LOG_FILE}" || true

log "current DeckSoundpad modules:"
capture_cmd pactl list modules short | grep -E "${SINK_NAME}|${MIC_NAME}|DeckSoundpad" | tee -a "${LOG_FILE}" || true

if is_truthy "${SKIP_PLAY}"; then
  log "sample playback skipped because DECKSOUNDPAD_POC_SKIP_PLAY=${SKIP_PLAY}"
else
  log "playing sample into ${SINK_NAME}; select '${MIC_DESC}' as input in Discord/Steam Voice/game"
  play_sample_to_virtual_mic || log "sample playback into virtual mic failed"
fi

log "PoC complete"
log "PASS condition: ${MIC_DESC} appears as an input source and its input meter reacts to sample playback."
log "Cleanup: scripts/poc_reset_audio.sh"
