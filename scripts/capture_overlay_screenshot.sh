#!/usr/bin/env bash
set -euo pipefail

# Captures the full gamescope composition on a Steam Deck in Game Mode, including
# the DeckSoundpad external overlay that Steam's own screenshot (Steam + R1) skips.
# Takes a screenshot every few seconds until a key is pressed in this terminal.
# Runs from macOS or Linux over SSH; the Deck needs sshd enabled.

DEFAULT_HOST="deck@192.168.0.13"
INTERVAL=10
COUNT=0
SHOT_TYPE=2
OUT_DIR="$HOME/Desktop/decksoundpad-screenshots"
MAX_FAILURES=3

usage() {
  cat <<EOF
Usage: $(basename "$0") [options] [user@host]

Takes a screenshot every INTERVAL seconds until you press any key here.

Options:
  -i SECONDS  time between screenshots, also the delay before the first (default: $INTERVAL)
  -n COUNT    stop after COUNT screenshots, 0 for no limit (default: $COUNT)
  -t TYPE     gamescope screenshot type: 2 full composition, 0 all real layers (default: $SHOT_TYPE)
  -o DIR      directory for the screenshots (default: $OUT_DIR)
  -h          show this help

The host defaults to \$DECK_HOST, then $DEFAULT_HOST.
EOF
}

while getopts ":i:n:t:o:h" opt; do
  case "$opt" in
    i) INTERVAL="$OPTARG" ;;
    n) COUNT="$OPTARG" ;;
    t) SHOT_TYPE="$OPTARG" ;;
    o) OUT_DIR="$OPTARG" ;;
    h)
      usage
      exit 0
      ;;
    :)
      echo "Option -$OPTARG needs a value" >&2
      usage >&2
      exit 2
      ;;
    *)
      echo "Unknown option: -$OPTARG" >&2
      usage >&2
      exit 2
      ;;
  esac
done
shift $((OPTIND - 1))
HOST="${1:-${DECK_HOST:-$DEFAULT_HOST}}"

if [[ ! "$INTERVAL" =~ ^[1-9][0-9]*$ ]]; then
  echo "-i must be a whole number of seconds, at least 1" >&2
  exit 2
fi
if [[ ! "$COUNT" =~ ^[0-9]+$ ]]; then
  echo "-n must be a whole number" >&2
  exit 2
fi
if [[ ! "$SHOT_TYPE" =~ ^[0-3]$ ]]; then
  echo "-t must be 0, 1, 2, or 3" >&2
  exit 2
fi
if ! (: </dev/tty) 2>/dev/null; then
  echo "This script needs an interactive terminal to watch for the stop key." >&2
  exit 2
fi

# Runs on the Deck as `check` or `capture TYPE PREFERRED`. stdout carries only the
# tar archive of a screenshot; progress and errors go to stderr, which ssh
# forwards to this terminal.
remote_script() {
  cat <<'REMOTE'
x11_root_prop() {
  # x11_root_prop --check | x11_root_prop ATOM VALUE
  if command -v xprop >/dev/null 2>&1; then
    if [[ "$1" == "--check" ]]; then
      xprop -root >/dev/null 2>&1
    else
      xprop -root -f "$1" 32c -set "$1" "$2"
    fi
    return
  fi
  python3 - "$@" <<'PY'
import ctypes
import sys

x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XDefaultRootWindow.restype = ctypes.c_ulong
x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x11.XInternAtom.restype = ctypes.c_ulong
x11.XChangeProperty.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_int,
]
x11.XFlush.argtypes = [ctypes.c_void_p]
x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

display = x11.XOpenDisplay(None)
if not display:
    sys.exit(1)
if sys.argv[1] != "--check":
    prop = x11.XInternAtom(display, sys.argv[1].encode(), 0)
    cardinal = x11.XInternAtom(display, b"CARDINAL", 0)
    value = ctypes.c_ulong(int(sys.argv[2]))
    # Format 32 data is passed as C longs; mode 0 is PropModeReplace.
    x11.XChangeProperty(display, x11.XDefaultRootWindow(display), prop, cardinal, 32, 0, ctypes.byref(value), 1)
    x11.XFlush(display)
x11.XCloseDisplay(display)
PY
}

wait_for_screenshot() {
  local marker="$1" tries=$(($2 * 4)) file size prev=""
  while ((tries-- > 0)); do
    file="$(find /tmp/ -maxdepth 1 -type f -name 'gamescope*' \( -name '*.png' -o -name '*.avif' \) -newer "$marker" -print -quit 2>/dev/null)"
    if [[ -n "$file" ]]; then
      # Return only once the size stops changing, so a half-written file is never copied.
      size="$(stat -c %s "$file")"
      if [[ "$size" -gt 0 && "$size" == "$prev" ]]; then
        printf '%s\n' "$file"
        return 0
      fi
      prev="$size"
    fi
    sleep 0.25
  done
  return 1
}

check() {
  if ! pgrep -x gamescope >/dev/null && ! pgrep -x gamescope-wl >/dev/null; then
    echo "warning: gamescope does not seem to be running; is the Deck in Game Mode?"
  fi
  if ! x11_root_prop --check; then
    echo "error: cannot open X display $DISPLAY (XAUTHORITY=${XAUTHORITY:-unset})"
    exit 1
  fi
}

capture() {
  local shot_type="$1" preferred="$2" atom tag file shot=""
  # The debug request writes the file without notifying Steam; the plain request
  # is the fallback for gamescope builds that only honour that one.
  local atoms=(GAMESCOPECTRL_DEBUG_REQUEST_SCREENSHOT GAMESCOPECTRL_REQUEST_SCREENSHOT)
  if [[ "$preferred" == request ]]; then
    atoms=(GAMESCOPECTRL_REQUEST_SCREENSHOT GAMESCOPECTRL_DEBUG_REQUEST_SCREENSHOT)
  fi

  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  touch "$WORK/marker"
  for atom in "${atoms[@]}"; do
    x11_root_prop "$atom" "$shot_type"
    if shot="$(wait_for_screenshot "$WORK/marker" 5)"; then
      break
    fi
    echo "No screenshot after $atom"
  done

  if [[ -z "$shot" ]]; then
    echo "error: gamescope did not write a screenshot to /tmp"
    echo "gamescope package: $(pacman -Q gamescope 2>/dev/null || echo unknown)"
    exit 1
  fi
  # The archived name tells the caller which request worked, so later captures
  # try that one first.
  tag=debug
  if [[ "$atom" == GAMESCOPECTRL_REQUEST_SCREENSHOT ]]; then
    tag=request
  fi
  file="$tag.${shot##*.}"
  cp "$shot" "$WORK/$file"
  tar -C "$WORK" -cf - "$file" >&3
}

main() {
  set -euo pipefail
  local candidate
  exec 3>&1 1>&2 </dev/null

  export DISPLAY=:0
  # Same Xauthority lookup the plugin uses when it launches the overlay.
  for candidate in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/gamescope/Xauthority" "$HOME/.Xauthority"; do
    if [[ -f "$candidate" ]]; then
      export XAUTHORITY="$candidate"
      break
    fi
  done

  case "$1" in
    check) check ;;
    capture) capture "$2" "$3" ;;
    *)
      echo "error: unknown command $1"
      exit 2
      ;;
  esac
}

main "$@"
REMOTE
}

# A short path keeps the ssh control socket under the unix socket length limit.
WORK_DIR="$(mktemp -d /tmp/decksoundpad-capture.XXXXXX)"
ARCHIVE="$WORK_DIR/screenshot.tar"
CONTROL_PATH="$WORK_DIR/ssh"
SSH_OPTS=(-o ConnectTimeout=10 -o ServerAliveInterval=15 -o ControlPath="$CONTROL_PATH")
TTY_SAVED=""

cleanup() {
  if [[ -n "$TTY_SAVED" ]]; then
    stty "$TTY_SAVED" <&4 2>/dev/null || true
  fi
  if [[ -S "$CONTROL_PATH" ]]; then
    ssh "${SSH_OPTS[@]}" -O exit "$HOST" 2>/dev/null || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Every call reuses the master connection, so the password is asked only once.
# BatchMode stops a dropped master from turning into a hidden password prompt.
run_remote() {
  remote_script | ssh "${SSH_OPTS[@]}" -o BatchMode=yes -T "$HOST" "bash -s -- $*"
}

# Counts down to the deadline; returns 1 as soon as a key is pressed.
wait_or_stop() {
  local deadline="$1" key
  while ((SECONDS < deadline)); do
    printf '\r\033[KNext screenshot in %ds, press any key to stop ' "$((deadline - SECONDS))"
    if read -rsn1 -t 1 key <&4; then
      printf '\r\033[K'
      return 1
    fi
  done
  printf '\r\033[K'
  return 0
}

save_screenshot() {
  local name ext base dest suffix=2
  name="$(tar -tf "$ARCHIVE" 2>/dev/null)" || return 1
  if [[ ! "$name" =~ ^(debug|request)\.(png|avif)$ ]]; then
    echo "Unexpected archive contents from the Deck: $name" >&2
    return 1
  fi
  PREFERRED="${name%%.*}"
  ext="${name##*.}"
  tar -xf "$ARCHIVE" -C "$WORK_DIR" || return 1
  mkdir -p "$OUT_DIR" || return 1

  base="$OUT_DIR/overlay-$(date +%Y%m%d-%H%M%S)"
  dest="$base.$ext"
  while [[ -e "$dest" ]]; do
    dest="$base-$suffix.$ext"
    suffix=$((suffix + 1))
  done
  mv "$WORK_DIR/$name" "$dest" || return 1
  echo "[$((SAVED + 1))] Saved $dest"
}

echo "Connecting to $HOST (the Deck must be in Game Mode with a game running)"
if ! ssh "${SSH_OPTS[@]}" -o ControlMaster=yes -o ControlPersist=yes -fN "$HOST"; then
  echo "Could not connect to $HOST" >&2
  exit 1
fi
if ! run_remote check; then
  echo "The Deck is not ready for screenshots, see the messages above." >&2
  exit 1
fi

exec 4</dev/tty
TTY_SAVED="$(stty -g <&4)"
# Keys pressed while a capture is running stay hidden and still stop the loop.
stty -echo <&4

echo "Connected. Open the overlay on the Deck; a screenshot is taken every ${INTERVAL}s."
SAVED=0
FAILURES=0
PREFERRED=debug
DEADLINE=$((SECONDS + INTERVAL))
while wait_or_stop "$DEADLINE"; do
  DEADLINE=$((SECONDS + INTERVAL))
  status=0
  run_remote capture "$SHOT_TYPE" "$PREFERRED" >"$ARCHIVE" || status=$?

  if [[ "$status" -eq 0 ]] && save_screenshot; then
    SAVED=$((SAVED + 1))
    FAILURES=0
    if [[ "$COUNT" -gt 0 && "$SAVED" -ge "$COUNT" ]]; then
      break
    fi
    continue
  fi

  if [[ "$status" -eq 255 ]]; then
    echo "Lost the SSH connection to $HOST" >&2
    break
  fi
  FAILURES=$((FAILURES + 1))
  if [[ "$FAILURES" -ge "$MAX_FAILURES" ]]; then
    echo "$MAX_FAILURES captures in a row failed, stopping." >&2
    break
  fi
done

if [[ "$SAVED" -eq 0 ]]; then
  echo "No screenshots saved."
  exit 1
fi
echo "Saved $SAVED screenshot(s) to $OUT_DIR"
