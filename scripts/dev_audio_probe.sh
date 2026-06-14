#!/usr/bin/env bash
set -euo pipefail

SINK_NAME="decksoundpad_sink"
MIC_NAME="decksoundpad_mic"
SINK_DESC="DeckSoundpad internal mix bus"
MIC_DESC="DeckSoundpad mic"
LOOPBACK_DESC="DeckSoundpad mic passthrough"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

need pactl

echo "pactl: $(command -v pactl)"
echo "pw-play: $(command -v pw-play || true)"
echo "ffmpeg: $(command -v ffmpeg || true)"
echo "mpv: $(command -v mpv || true)"

if ! pactl list sinks short | awk '{print $2}' | grep -Fxq "${SINK_NAME}"; then
  pactl load-module module-null-sink \
    "sink_name=${SINK_NAME}" \
    "sink_properties=device.description=${SINK_DESC}"
fi

if ! pactl list sources short | awk '{print $2}' | grep -Fxq "${MIC_NAME}"; then
  pactl load-module module-virtual-source \
    "master=${SINK_NAME}.monitor" \
    "source_name=${MIC_NAME}" \
    "source_properties=device.description=${MIC_DESC}" || \
  pactl load-module module-remap-source \
    "master=${SINK_NAME}.monitor" \
    "source_name=${MIC_NAME}" \
    "source_properties=device.description=${MIC_DESC}"
fi

REAL_SOURCE="$(
  pactl get-default-source 2>/dev/null || true
)"

if [[ "${REAL_SOURCE}" == "${MIC_NAME}" || "${REAL_SOURCE}" == "${SINK_NAME}.monitor" || "${REAL_SOURCE}" == *.monitor ]]; then
  REAL_SOURCE="$(
    pactl list sources short |
      awk '{print $2}' |
      grep -v -Fx "${MIC_NAME}" |
      grep -v -Fx "${SINK_NAME}.monitor" |
      grep -v '\.monitor$' |
      head -n 1
  )"
fi

if [[ -n "${REAL_SOURCE}" ]]; then
  if ! pactl list modules short | grep -F "module-loopback" | grep -Fq "sink=${SINK_NAME}"; then
    pactl load-module module-loopback \
      "source=${REAL_SOURCE}" \
      "sink=${SINK_NAME}" \
      "latency_msec=20" \
      "source_output_properties=media.name=${LOOPBACK_DESC}"
  fi
  echo "real mic passthrough: ${REAL_SOURCE}"
else
  echo "no real mic source found; virtual mic is soundboard-only" >&2
fi

echo "sources:"
pactl list sources short | grep -E "${MIC_NAME}|${SINK_NAME}|alsa_input|bluez_input" || true

if [[ "${1:-}" != "" ]]; then
  if [[ "${1}" == *.wav || "${1}" == *.WAV ]]; then
    SAMPLE_NAME="decksoundpad_probe_$$_$(date +%s)"
    pactl upload-sample "$1" "${SAMPLE_NAME}"
    pactl play-sample "${SAMPLE_NAME}" "${SINK_NAME}"
    sleep 1
    pactl remove-sample "${SAMPLE_NAME}" || true
  elif command -v pw-play >/dev/null 2>&1; then
    pw-play "--target=${SINK_NAME}" "$1"
  else
    echo "pw-play unavailable; cannot play test file" >&2
    exit 1
  fi
fi
