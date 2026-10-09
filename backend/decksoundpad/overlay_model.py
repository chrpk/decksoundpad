"""Overlay state helpers: tabs, cursor movement, Recent sounds, and mic status.

The bridge in ``main.py`` owns the overlay state; these helpers stay pure so the
navigation rules can be tested without input devices or a display.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .overlay_layout import GRID_COLUMNS, SOUNDS_PER_PAGE
from .safe_files import open_regular_file

RECENT_TAB_KEY = "recent"
ALL_TAB_KEY = "all"
CATEGORY_TAB_PREFIX = "category:"
# Matches the category the library assigns to files directly in a sound folder.
ROOT_CATEGORY = "uncategorized"
RECENT_TAB_LIMIT = 10
RECENT_STORE_LIMIT = 20

TONE_OK = "ok"
TONE_WARN = "warn"
TONE_ERROR = "error"


@dataclass(frozen=True)
class OverlayTab:
    key: str
    label: str
    sounds: tuple[dict[str, Any], ...]

    @property
    def page_count(self) -> int:
        return max(1, -(-len(self.sounds) // SOUNDS_PER_PAGE))


def build_tabs(
    sounds: Sequence[dict[str, Any]], recent_ids: Iterable[str]
) -> list[OverlayTab]:
    """Return Recent (when any recent sound still exists) and one tab per folder."""

    by_id = {sound["id"]: sound for sound in sounds if isinstance(sound.get("id"), str)}
    tabs: list[OverlayTab] = []
    recent = [by_id[sound_id] for sound_id in recent_ids if sound_id in by_id][
        :RECENT_TAB_LIMIT
    ]
    if recent:
        tabs.append(OverlayTab(RECENT_TAB_KEY, "Recent", tuple(recent)))

    categories: dict[str, list[dict[str, Any]]] = {}
    for sound in sounds:
        categories.setdefault(str(sound.get("category") or ROOT_CATEGORY), []).append(
            sound
        )
    if len(categories) <= 1:
        tabs.append(OverlayTab(ALL_TAB_KEY, "All sounds", tuple(sounds)))
        return tabs

    # Loose files in the sound folder go last, after the named folders.
    for name in sorted(categories, key=lambda category: category == ROOT_CATEGORY):
        label = "Other" if name == ROOT_CATEGORY else name
        tabs.append(
            OverlayTab(f"{CATEGORY_TAB_PREFIX}{name}", label, tuple(categories[name]))
        )
    return tabs


def move_horizontal(index: int, count: int, direction: int) -> int:
    """Step through the tab in reading order, flowing across rows and pages."""

    if count <= 0:
        return 0
    return (index + direction) % count


def move_vertical(index: int, count: int, direction: int) -> int:
    """Move one grid row, flowing across pages and wrapping at the ends of the tab."""

    if count <= 0:
        return 0
    index = max(0, min(index, count - 1))
    row, column = divmod(index, GRID_COLUMNS)
    last_row = (count - 1) // GRID_COLUMNS
    if direction > 0:
        if index + GRID_COLUMNS < count:
            return index + GRID_COLUMNS
        if row < last_row:
            # The next row is partial; land on its last sound.
            return count - 1
        return min(column, count - 1)
    if index - GRID_COLUMNS >= 0:
        return index - GRID_COLUMNS
    return min(last_row * GRID_COLUMNS + column, count - 1)


def flip_page(
    tabs: Sequence[OverlayTab],
    tab_index: int,
    cursor: int,
    direction: int,
) -> tuple[int, int]:
    """Move one page, crossing into the neighbouring tab at either end.

    The cursor keeps its row and column on the new page when that tile exists.
    """

    if not tabs:
        return 0, 0
    tab_index = max(0, min(tab_index, len(tabs) - 1))
    page, offset = divmod(max(0, cursor), SOUNDS_PER_PAGE)
    page += direction
    if page < 0:
        tab_index = (tab_index - 1) % len(tabs)
        page = tabs[tab_index].page_count - 1
    elif page >= tabs[tab_index].page_count:
        tab_index = (tab_index + 1) % len(tabs)
        page = 0
    return tab_index, clamp_cursor(
        page * SOUNDS_PER_PAGE + offset, len(tabs[tab_index].sounds)
    )


def clamp_cursor(cursor: int, count: int) -> int:
    return max(0, min(cursor, count - 1)) if count > 0 else 0


def push_recent(recent_ids: Sequence[str], sound_id: str) -> list[str]:
    return [sound_id, *(existing for existing in recent_ids if existing != sound_id)][
        :RECENT_STORE_LIMIT
    ]


def load_recent_ids(path: Path) -> list[str]:
    try:
        with open_regular_file(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    ids = data.get("sound_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        return []
    return [sound_id for sound_id in ids if isinstance(sound_id, str)][
        :RECENT_STORE_LIMIT
    ]


def save_recent_ids(
    path: Path, recent_ids: Sequence[str], *, owner: tuple[int, int] | None = None
) -> None:
    with open_regular_file(
        path,
        "w",
        encoding="utf-8",
        permissions=0o600,
        enforce_permissions=True,
        owner=owner,
    ) as handle:
        json.dump({"sound_ids": list(recent_ids[:RECENT_STORE_LIMIT])}, handle)
        handle.write("\n")


def sound_label(sound: Mapping[str, Any]) -> str:
    return str(sound.get("display_name") or sound.get("relative_path") or "Sound")


def summarize_mic_status(status: Any) -> dict[str, str]:
    """Condense a backend status payload into the overlay's mic indicator.

    Mirrors the Decky status card so both surfaces agree on what needs a restart.
    """

    if not isinstance(status, Mapping) or not status.get("backend_running"):
        return {"tone": TONE_ERROR, "label": "Audio offline"}
    audio = status.get("audio")
    if not isinstance(audio, Mapping):
        return {"tone": TONE_WARN, "label": "Checking audio"}
    state = audio.get("state")
    if state in {"starting", "repairing"}:
        return {"tone": TONE_WARN, "label": "Audio restarting"}
    if state == "pending" or audio.get("last_error") == "Audio status pending":
        return {"tone": TONE_WARN, "label": "Checking audio"}
    if not audio.get("pactl_available") or not audio.get("pipewire_available"):
        return {"tone": TONE_ERROR, "label": "PipeWire unavailable"}
    if state == "ready":
        return {"tone": TONE_OK, "label": "Mic ready"}
    if not audio.get("sink_exists") or not audio.get("virtual_mic_exists"):
        return {"tone": TONE_ERROR, "label": "Mic not set up · restart in Decky"}
    if not audio.get("selected_real_mic"):
        # Soundboard playback still reaches the virtual mic without a real mic.
        return {"tone": TONE_OK, "label": "Mic ready · no real mic"}
    if state == "needs_repair" or not audio.get("loopback_exists"):
        return {"tone": TONE_WARN, "label": "Needs restart in Decky"}
    return {"tone": TONE_WARN, "label": "Check DeckSoundpad in Decky"}


def display_library_dir(status: Any, user_home: Path) -> str | None:
    library = status.get("library") if isinstance(status, Mapping) else None
    dirs = library.get("dirs") if isinstance(library, Mapping) else None
    if not isinstance(dirs, list) or not dirs or not isinstance(dirs[0], str):
        return None
    folder = Path(dirs[0])
    try:
        return f"~/{folder.relative_to(user_home).as_posix()}"
    except ValueError:
        return str(folder)
