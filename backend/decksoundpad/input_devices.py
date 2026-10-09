"""Linux evdev/hidraw helpers for overlay hotkeys and controller navigation."""

from __future__ import annotations

import hashlib
import os
import select
import struct
import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - SteamOS/Linux always has fcntl.
    fcntl = None  # type: ignore[assignment]

EV_KEY = 0x01
KEY_MAX = 0x2FF
BTN_GRIPL = 0x224
BTN_GRIPR = 0x225
BTN_GRIPL2 = 0x226
BTN_GRIPR2 = 0x227
BTN_SOUTH = 0x130
BTN_EAST = 0x131
# Named after the printed labels, as Xbox-style drivers (including Steam's
# virtual pad) report them; the kernel also aliases these to BTN_NORTH/BTN_WEST.
BTN_X = 0x133
BTN_Y = 0x134
BTN_TL = 0x136
BTN_TR = 0x137
BTN_TL2 = 0x138
BTN_TRIGGER_HAPPY1 = 0x2C0
BTN_TRIGGER_HAPPY40 = 0x2E7
BTN_DPAD_UP = 0x220
BTN_DPAD_DOWN = 0x221
BTN_DPAD_LEFT = 0x222
BTN_DPAD_RIGHT = 0x223
INPUT_EVENT_STRUCT = struct.Struct("llHHI")
INPUT_EVENT_SIZE = INPUT_EVENT_STRUCT.size
INPUT_EVENT_READ_BATCH = 64
EVIOCGRAB = 0x40044590
EVIOCGNAME = 0x06
EVIOCGPHYS = 0x07
EVIOCGUNIQ = 0x08
EVIOCGBIT_BASE = 0x20

STEAM_DECK_REAR_BUTTON_MASKS = {
    "l4": 1 << 41,
    "l5": 1 << 15,
    "r4": 1 << 42,
    "r5": 1 << 16,
}
STEAM_DECK_REAR_BUTTON_EVENT_CODES = {
    "l4": frozenset({BTN_GRIPL}),
    "l5": frozenset({BTN_GRIPL2}),
    "r4": frozenset({BTN_GRIPR}),
    "r5": frozenset({BTN_GRIPR2}),
}
LEGACY_L5_EVENT_CODES = frozenset(
    {
        BTN_GRIPL,
        BTN_GRIPL2,
        BTN_TL2,
        *range(BTN_TRIGGER_HAPPY1, BTN_TRIGGER_HAPPY40 + 1),
    }
)
OVERLAY_HOTKEY_BUTTONS = frozenset(STEAM_DECK_REAR_BUTTON_MASKS)
KEY_NAMES = {
    BTN_SOUTH: "BTN_SOUTH/A",
    BTN_EAST: "BTN_EAST/B",
    BTN_X: "BTN_X",
    BTN_Y: "BTN_Y",
    BTN_TL: "BTN_TL/L1",
    BTN_TR: "BTN_TR/R1",
    BTN_DPAD_UP: "BTN_DPAD_UP",
    BTN_DPAD_DOWN: "BTN_DPAD_DOWN",
    BTN_DPAD_LEFT: "BTN_DPAD_LEFT",
    BTN_DPAD_RIGHT: "BTN_DPAD_RIGHT",
    BTN_GRIPL: "BTN_GRIPL/L4",
    BTN_GRIPR: "BTN_GRIPR/R4",
    BTN_GRIPL2: "BTN_GRIPL2/L5",
    BTN_GRIPR2: "BTN_GRIPR2/R5",
}
EVDEV_OVERLAY_ACTIONS = {
    BTN_SOUTH: "play",
    BTN_X: "play_stay",
    BTN_Y: "stop",
    BTN_EAST: "hide",
    BTN_DPAD_UP: "up",
    BTN_DPAD_DOWN: "down",
    BTN_DPAD_LEFT: "left",
    BTN_DPAD_RIGHT: "right",
    BTN_TL: "page_prev",
    BTN_TR: "page_next",
}

# Targets returned by classify_overlay_key_press besides overlay actions.
TOGGLE_OVERLAY = "toggle"
REPLAY_LAST_SOUND = "replay_last"

STEAM_DECK_HID_REPORT_VERSION = 0x01
STEAM_DECK_HID_DECK_STATE_TYPE = 0x09
STEAM_DECK_LBUTTON_R = 0x00000004
STEAM_DECK_LBUTTON_L = 0x00000008
STEAM_DECK_LBUTTON_Y = 0x00000010
STEAM_DECK_LBUTTON_B = 0x00000020
STEAM_DECK_LBUTTON_X = 0x00000040
STEAM_DECK_LBUTTON_A = 0x00000080
STEAM_DECK_LBUTTON_DPAD_UP = 0x00000100
STEAM_DECK_LBUTTON_DPAD_RIGHT = 0x00000200
STEAM_DECK_LBUTTON_DPAD_LEFT = 0x00000400
STEAM_DECK_LBUTTON_DPAD_DOWN = 0x00000800
STEAM_DECK_LBUTTON_R5 = STEAM_DECK_REAR_BUTTON_MASKS["r5"]
STEAM_DECK_HID_ACTIONS = (
    (STEAM_DECK_LBUTTON_A, "play"),
    (STEAM_DECK_LBUTTON_X, "play_stay"),
    (STEAM_DECK_LBUTTON_Y, "stop"),
    (STEAM_DECK_LBUTTON_B, "hide"),
    (STEAM_DECK_LBUTTON_DPAD_RIGHT, "right"),
    (STEAM_DECK_LBUTTON_DPAD_DOWN, "down"),
    (STEAM_DECK_LBUTTON_DPAD_LEFT, "left"),
    (STEAM_DECK_LBUTTON_DPAD_UP, "up"),
    (STEAM_DECK_LBUTTON_L, "page_prev"),
    (STEAM_DECK_LBUTTON_R, "page_next"),
)
HIDRAW_REPORT_SIZE = 64
HIDRAW_STICK_NAVIGATION_THRESHOLD = 14500
VALVE_USB_VENDOR_ID = 0x28DE
SYSFS_HIDRAW_DIR = Path("/sys/class/hidraw")

OVERLAY_INPUT_GRAB_NAME_HINTS = (
    "steam deck",
    "steam controller",
    "x-box",
    "xbox",
    "gamepad",
    "controller",
    "wireless controller",
    "dualsense",
    "dualshock",
    "playstation",
    "nintendo",
    "pro controller",
    "8bitdo",
    "neptune",
    "jupiter",
    "galileo",
    "joy",
)
OVERLAY_INPUT_GRAB_NAME_EXCLUDES = (
    "keyboard",
    "mouse",
    "touchpad",
    "touchscreen",
    "power button",
    "lid switch",
)
OVERLAY_NAVIGATION_CODES = frozenset(EVDEV_OVERLAY_ACTIONS)
OVERLAY_HOTKEY_CODES = LEGACY_L5_EVENT_CODES.union(
    *STEAM_DECK_REAR_BUTTON_EVENT_CODES.values()
)

AUTO_INPUT_DEVICE = "auto"

DeviceHandles = list[tuple[str, Any]]


def normalize_overlay_hotkey_button(button: object) -> str:
    value = str(button or "").lower()
    return value if value in OVERLAY_HOTKEY_BUTTONS else "l5"


def normalize_overlay_input_device(selector: object) -> str:
    value = str(selector or "").lower()
    return value if value.startswith("evdev:") else AUTO_INPUT_DEVICE


def overlay_hotkey_event_codes(
    button: object,
    *,
    include_legacy_l5: bool = False,
) -> frozenset[int]:
    normalized = normalize_overlay_hotkey_button(button)
    if normalized == "l5" and include_legacy_l5:
        return LEGACY_L5_EVENT_CODES
    return STEAM_DECK_REAR_BUTTON_EVENT_CODES[normalized]


def overlay_hotkey_button_mask(button: object) -> int:
    return STEAM_DECK_REAR_BUTTON_MASKS[normalize_overlay_hotkey_button(button)]


def classify_overlay_key_press(
    code: int,
    hotkey_button: str,
    *,
    include_legacy_l5: bool,
) -> str | None:
    """Map an evdev key code to TOGGLE_OVERLAY, REPLAY_LAST_SOUND or an overlay action."""

    if code in overlay_hotkey_event_codes(
        hotkey_button, include_legacy_l5=include_legacy_l5
    ):
        return TOGGLE_OVERLAY
    if code in EVDEV_OVERLAY_ACTIONS:
        return EVDEV_OVERLAY_ACTIONS[code]
    if hotkey_button != "r5" and code in STEAM_DECK_REAR_BUTTON_EVENT_CODES["r5"]:
        return REPLAY_LAST_SOUND
    return None


def classify_steam_deck_hid_press(pressed: int, hotkey_button: str) -> str | None:
    """Map newly pressed Steam Deck HID buttons to the same targets as evdev presses."""

    if pressed & overlay_hotkey_button_mask(hotkey_button):
        return TOGGLE_OVERLAY
    if hotkey_button != "r5" and pressed & STEAM_DECK_LBUTTON_R5:
        return REPLAY_LAST_SOUND
    for mask, action in STEAM_DECK_HID_ACTIONS:
        if pressed & mask:
            return action
    return None


def parse_steam_deck_hid_report(data: bytes) -> dict[str, int] | None:
    for offset in (0, 1):
        # Some hidraw reads include a leading report id byte and some do not.
        if len(data) < offset + 16:
            continue
        version, report_type = struct.unpack_from("<HB", data, offset)
        if version != STEAM_DECK_HID_REPORT_VERSION:
            continue
        if report_type != STEAM_DECK_HID_DECK_STATE_TYPE:
            continue
        buttons_l, buttons_h = struct.unpack_from("<II", data, offset + 8)
        report = {"offset": offset, "buttons_l": buttons_l, "buttons_h": buttons_h}
        if len(data) >= offset + 56:
            left_x, raw_left_y, right_x, raw_right_y = struct.unpack_from(
                "<hhhh", data, offset + 48
            )
            report.update(
                {
                    "left_stick_x": left_x,
                    "left_stick_y": -raw_left_y,
                    "right_stick_x": right_x,
                    "right_stick_y": -raw_right_y,
                }
            )
        return report
    return None


def hidraw_vendor_id(
    path: str | Path, sysfs_dir: Path = SYSFS_HIDRAW_DIR
) -> int | None:
    """Return the USB vendor id sysfs reports for a hidraw node, if readable."""

    try:
        uevent = (sysfs_dir / Path(path).name / "device" / "uevent").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return None
    for line in uevent.splitlines():
        # HID_ID=<bus>:<vendor>:<product>, for example 0003:000028DE:00001205.
        if line.startswith("HID_ID="):
            parts = line.removeprefix("HID_ID=").split(":")
            if len(parts) == 3:
                try:
                    return int(parts[1], 16)
                except ValueError:
                    return None
    return None


def is_valve_hidraw_device(
    path: str | Path, sysfs_dir: Path = SYSFS_HIDRAW_DIR
) -> bool:
    """Only Valve controllers send Steam Deck state reports.

    Other controllers stream their own reports continuously, so reading them
    only costs wakeups. Nodes whose vendor is unknown stay eligible so a missing
    sysfs cannot disable the hotkey.
    """

    vendor = hidraw_vendor_id(path, sysfs_dir)
    return vendor is None or vendor == VALVE_USB_VENDOR_ID


def dominant_steam_deck_stick_direction(report: dict[str, int]) -> str | None:
    left_x = int(report.get("left_stick_x", 0))
    left_y = int(report.get("left_stick_y", 0))
    right_x = int(report.get("right_stick_x", 0))
    right_y = int(report.get("right_stick_y", 0))
    left_magnitude = max(abs(left_x), abs(left_y))
    right_magnitude = max(abs(right_x), abs(right_y))
    if max(left_magnitude, right_magnitude) < HIDRAW_STICK_NAVIGATION_THRESHOLD:
        return None

    # Use whichever stick is pushed farther so accidental drift on the other
    # stick does not steal overlay navigation.
    x, y = (right_x, right_y) if right_magnitude > left_magnitude else (left_x, left_y)
    if abs(x) >= abs(y):
        return "right" if x > 0 else "left"
    return "down" if y > 0 else "up"


def open_nonblocking(path: str | Path) -> Any:
    handle = Path(path).open("rb", buffering=0)
    try:
        os.set_blocking(handle.fileno(), False)
    except OSError:
        close_quietly(handle)
        raise
    return handle


def close_quietly(handle: Any) -> None:
    try:
        handle.close()
    except OSError:
        pass


def open_device_paths(
    paths: Iterable[str | Path],
    on_error: Callable[[str, OSError], None],
) -> DeviceHandles:
    """Open each path non-blocking, reporting failures through ``on_error``."""

    handles: DeviceHandles = []
    for path in paths:
        try:
            handles.append((str(path), open_nonblocking(path)))
        except OSError as exc:
            on_error(str(path), exc)
    return handles


def set_device_grab(handle: Any, grabbed: bool) -> None:
    """Grab or release exclusive evdev access; raises OSError when unavailable."""

    if fcntl is None:
        raise OSError("fcntl unavailable")
    fcntl.ioctl(handle.fileno(), EVIOCGRAB, 1 if grabbed else 0)


def close_device_handles(handles: DeviceHandles) -> None:
    for _path, handle in handles:
        close_quietly(handle)


def read_ready_devices(
    handles: DeviceHandles,
    *,
    size: int,
    timeout: float,
    min_size: int = 1,
    stop: threading.Event | None = None,
) -> Iterator[tuple[str, bytes]]:
    """Wait for readable handles and yield every pending ``(path, chunk)`` read.

    A read shorter than ``min_size`` ends the drain for that handle. OSError
    propagates so callers can reopen devices that disappeared.
    """

    readable, _writable, _errored = select.select(
        [handle for _path, handle in handles], [], [], timeout
    )
    for handle in readable:
        device_path = next(
            (path for path, candidate in handles if candidate is handle), "<unknown>"
        )
        while stop is None or not stop.is_set():
            try:
                data = os.read(handle.fileno(), size)
            except BlockingIOError:
                break
            if len(data) < min_size:
                break
            yield device_path, data


def read_key_presses(
    handles: DeviceHandles,
    *,
    timeout: float,
    stop: threading.Event | None = None,
) -> Iterator[tuple[str, int]]:
    """Yield ``(path, key code)`` for each EV_KEY press read from evdev handles."""

    # evdev reads always return whole events, so batch them per syscall.
    for device_path, data in read_ready_devices(
        handles,
        size=INPUT_EVENT_SIZE * INPUT_EVENT_READ_BATCH,
        min_size=INPUT_EVENT_SIZE,
        timeout=timeout,
        stop=stop,
    ):
        usable = len(data) - len(data) % INPUT_EVENT_SIZE
        for _sec, _usec, event_type, code, value in INPUT_EVENT_STRUCT.iter_unpack(
            data[:usable]
        ):
            if event_type == EV_KEY and value == 1:
                yield device_path, code


def evioc_read(number: int, length: int) -> int:
    # Linux _IOC(_IOC_READ, 'E', number, length)
    return (2 << 30) | (length << 16) | (ord("E") << 8) | number


def input_device_property(handle: Any, number: int) -> str:
    if fcntl is None:
        return ""
    buffer = bytearray(256)
    try:
        fcntl.ioctl(handle.fileno(), evioc_read(number, len(buffer)), buffer, True)
    except OSError:
        return ""
    raw = bytes(buffer).split(b"\x00", 1)[0]
    return raw.decode("utf-8", errors="replace")


def input_device_key_capabilities(handle: Any) -> frozenset[int]:
    if fcntl is None:
        return frozenset()
    buffer = bytearray((KEY_MAX + 8) // 8)
    try:
        fcntl.ioctl(
            handle.fileno(),
            evioc_read(EVIOCGBIT_BASE + EV_KEY, len(buffer)),
            buffer,
            True,
        )
    except OSError:
        return frozenset()
    return frozenset(
        code for code in range(KEY_MAX + 1) if buffer[code // 8] & (1 << (code % 8))
    )


def is_overlay_input_device_name_relevant(name: str) -> bool:
    lowered = name.lower()
    if not lowered:
        return False
    if any(fragment in lowered for fragment in OVERLAY_INPUT_GRAB_NAME_EXCLUDES):
        return False
    return any(fragment in lowered for fragment in OVERLAY_INPUT_GRAB_NAME_HINTS)


def is_overlay_input_device_relevant(name: str, capabilities: frozenset[int]) -> bool:
    if not is_overlay_input_device_name_relevant(name):
        return False
    return bool(capabilities & OVERLAY_NAVIGATION_CODES) and bool(
        capabilities & OVERLAY_HOTKEY_CODES
    )


def make_input_device_selector(name: str, phys: str, uniq: str) -> str | None:
    # Raw event paths are never part of the persisted identity.
    normalized_phys = phys.strip()
    normalized_uniq = uniq.strip()
    if not normalized_phys and not normalized_uniq:
        return None
    identity = "\0".join((name.strip(), normalized_phys, normalized_uniq))
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"evdev:{digest}"


def deduplicate_overlay_input_devices(
    devices: list[dict[str, str]],
) -> list[dict[str, str]]:
    deduplicated: list[dict[str, str]] = []
    seen_selectors: set[str] = set()
    for device in devices:
        selector = device.get("id", "")
        if selector in seen_selectors:
            continue
        if selector:
            seen_selectors.add(selector)
        deduplicated.append(device)
    return deduplicated


def filter_overlay_input_devices(
    devices: list[dict[str, str]],
    selector: str,
) -> list[dict[str, str]]:
    if selector == AUTO_INPUT_DEVICE:
        return devices
    return [device for device in devices if device.get("id") == selector]


def discover_overlay_input_devices(
    input_dir: Path = Path("/dev/input"),
) -> list[dict[str, str]]:
    try:
        event_paths = sorted(input_dir.glob("event*"))
    except OSError:
        return []

    devices: list[dict[str, str]] = []
    for path in event_paths:
        try:
            handle = path.open("rb", buffering=0)
        except OSError:
            continue
        try:
            # Check the name first so unrelated devices skip the capability ioctl.
            name = input_device_property(handle, EVIOCGNAME)
            if not is_overlay_input_device_name_relevant(name):
                continue
            if not is_overlay_input_device_relevant(
                name, input_device_key_capabilities(handle)
            ):
                continue
            phys = input_device_property(handle, EVIOCGPHYS)
            uniq = input_device_property(handle, EVIOCGUNIQ)
        finally:
            close_quietly(handle)
        path_text = str(path)
        devices.append(
            {
                "id": make_input_device_selector(name, phys, uniq) or "",
                "name": name,
                "path": path_text,
                "label": f"{name} ({path.name})",
            }
        )
    devices.sort(key=lambda device: (device["label"].lower(), device["path"]))
    return deduplicate_overlay_input_devices(devices)
