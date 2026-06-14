#!/usr/bin/env bash
set -euo pipefail

SINK_NAME="decksoundpad_sink"
MIC_NAME="decksoundpad_mic"
SINK_DESC="DeckSoundpad internal mix bus"
MIC_DESC="DeckSoundpad mic"
LOOPBACK_DESC="DeckSoundpad mic passthrough"

if ! command -v pactl >/dev/null 2>&1; then
  echo "pactl not found" >&2
  exit 1
fi

MODULE_IDS="$(
  pactl list modules short |
    grep -E "${SINK_NAME}|${MIC_NAME}|${SINK_DESC}|${MIC_DESC}|${LOOPBACK_DESC}" |
    awk '{print $1}' |
    sort -rn || true
)"

if [[ -z "${MODULE_IDS}" ]]; then
  echo "no DeckSoundpad modules found"
  exit 0
fi

while read -r module_id; do
  [[ -n "${module_id}" ]] || continue
  echo "unloading DeckSoundpad module ${module_id}"
  pactl unload-module "${module_id}" || true
done <<< "${MODULE_IDS}"
