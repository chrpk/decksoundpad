from __future__ import annotations

import argparse
import ctypes
import json
import logging
import math
import os
import socket
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("GdkX11", "3.0")
except ValueError:
    pass

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

try:
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo  # noqa: E402
except (ImportError, ValueError):
    # Without Pango, text falls back to cairo's toy API: single-line labels and
    # no font fallback for non-Latin sound names.
    Pango = None
    PangoCairo = None

# This file runs as a script from backend/decksoundpad; make the package importable.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from decksoundpad.overlay_layout import (  # noqa: E402
    HIT_OUTSIDE,
    HIT_TAB,
    HIT_TILE,
    SOUNDS_PER_PAGE,
    OverlayLayout,
    Rect,
    hit_test,
    overlay_layout,
    visible_tab_range,
)

LOGGER = logging.getLogger("decksoundpad.external_overlay")
GAMESCOPE_OVERLAY_ATOMS = ("GAMESCOPE_EXTERNAL_OVERLAY", "STEAM_EXTERNAL_OVERLAY")
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
FONT_FAMILY = "Sans"
TOAST_SECONDS = 1.8
POINTER_REPEAT_SECONDS = 0.25

Color = tuple[float, float, float, float]

TEXT_PRIMARY: Color = (0.96, 0.98, 1.0, 1.0)
TEXT_SECONDARY: Color = (0.80, 0.86, 0.89, 1.0)
TEXT_MUTED: Color = (0.64, 0.72, 0.76, 1.0)
TEXT_ON_LIGHT: Color = (0.05, 0.07, 0.09, 1.0)
TEXT_ON_LIGHT_MUTED: Color = (0.05, 0.07, 0.09, 0.62)
# The game shows through only around the panels and tiles, which stay near
# opaque so text keeps its contrast over bright scenes.
BACKDROP: Color = (0.02, 0.03, 0.04, 0.66)
PANEL: Color = (0.04, 0.05, 0.07, 0.90)
TOAST_FILL: Color = (0.04, 0.05, 0.07, 0.92)
DIVIDER: Color = (0.30, 0.72, 0.82, 0.38)
TILE_FILL: Color = (0.10, 0.12, 0.15, 0.88)
TILE_BORDER: Color = (1.0, 1.0, 1.0, 0.10)
TILE_SELECTED_FILL: Color = (0.10, 0.40, 0.48, 0.96)
FOCUS_RING: Color = (0.94, 0.98, 1.0, 1.0)
GLYPH_FILL: Color = (0.92, 0.95, 0.97, 1.0)
TAB_FILL: Color = (1.0, 1.0, 1.0, 0.08)
TAB_BORDER: Color = (1.0, 1.0, 1.0, 0.16)
PLAYING: Color = (0.42, 0.88, 0.56, 1.0)
TONE_COLORS: dict[str, Color] = {
    "ok": (0.42, 0.88, 0.56, 1.0),
    "warn": (1.0, 0.78, 0.35, 1.0),
    "error": (1.0, 0.50, 0.44, 1.0),
    "info": (0.55, 0.80, 0.95, 1.0),
    "play": (0.42, 0.88, 0.56, 1.0),
}

TILE_RADIUS = 8
TILE_TEXT_INSET = 14
TAB_GAP = 8
TAB_PADDING = 14
FACE_BUTTONS = frozenset({"A", "B", "X", "Y"})


class XAtomSetter:
    def __init__(self) -> None:
        self._lib = None
        try:
            self._lib = ctypes.cdll.LoadLibrary("libX11.so.6")
            self._lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self._lib.XOpenDisplay.restype = ctypes.c_void_p
            self._lib.XInternAtom.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_int,
            ]
            self._lib.XInternAtom.restype = ctypes.c_ulong
            self._lib.XChangeProperty.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            self._lib.XFlush.argtypes = [ctypes.c_void_p]
            self._lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        except OSError as exc:
            LOGGER.warning("libX11 unavailable: %s", exc)

    def set_cardinal(self, xid: int, atom_name: str, value: int) -> bool:
        if self._lib is None:
            return False

        display_name = os.environ.get("DISPLAY")
        display = self._lib.XOpenDisplay(
            display_name.encode("utf-8") if display_name else None
        )
        if not display:
            LOGGER.warning("XOpenDisplay failed display=%s", display_name)
            return False

        try:
            property_atom = self._lib.XInternAtom(display, atom_name.encode("utf-8"), 0)
            cardinal_atom = self._lib.XInternAtom(display, b"CARDINAL", 0)
            data = ctypes.c_ulong(value)
            self._lib.XChangeProperty(
                display,
                ctypes.c_ulong(xid),
                property_atom,
                cardinal_atom,
                32,
                0,
                ctypes.cast(ctypes.pointer(data), ctypes.c_void_p),
                1,
            )
            self._lib.XFlush(display)
            return True
        finally:
            self._lib.XCloseDisplay(display)


class OverlayWindow(Gtk.Window):
    def __init__(self, socket_path: Path, actions_socket_path: Path | None) -> None:
        super().__init__(type=Gtk.WindowType.POPUP)
        self.socket_path = socket_path
        self.actions_socket_path = actions_socket_path
        self.visible_overlay = False
        self.state: dict[str, Any] = {
            "visible": False,
            "sounds": [],
            "selected_index": 0,
            "page": 0,
            "page_count": 1,
            "total_count": 0,
            "tabs": [],
            "tab_index": 0,
            "playing_ids": [],
            "message": "",
        }
        self.toast: dict[str, Any] | None = None
        self._toast_token = 0
        self._tab_rects: list[tuple[Rect, int]] = []
        self.xatoms_enabled = False
        self.xatom_setter = XAtomSetter()
        self._server_thread: threading.Thread | None = None
        self._server_stop = threading.Event()
        self._last_pointer_action_at = 0.0
        self._last_pointer_action_index = -1
        self._input_passthrough: bool | None = None

        self.set_title("DeckSoundpad Overlay")
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_skip_pager_hint(True)
        self.set_skip_taskbar_hint(True)
        event_mask = Gdk.EventMask.BUTTON_PRESS_MASK
        touch_mask = getattr(Gdk.EventMask, "TOUCH_MASK", 0)
        event_mask |= touch_mask
        self.add_events(event_mask)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("touch-event", self.on_touch_event)
        self.connect("destroy", self.on_destroy)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        self.resize_to_monitor()
        self.show_all()
        self.set_input_passthrough(True)
        self.hide()
        self.start_socket_server()

    def resize_to_monitor(self) -> None:
        display = Gdk.Display.get_default()
        monitor = (
            display.get_monitor(0) if display and display.get_n_monitors() else None
        )
        if monitor:
            geometry = monitor.get_geometry()
            self.move(geometry.x, geometry.y)
            self.resize(geometry.width, geometry.height)
            return
        self.move(0, 0)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def set_input_passthrough(self, enabled: bool) -> None:
        # Every state update calls this, so skip the X request when unchanged.
        if enabled == self._input_passthrough:
            return
        self._input_passthrough = enabled
        # An empty input shape lets games receive clicks while the hidden overlay
        # window remains alive above them; None restores whole-window input.
        self.input_shape_combine_region(cairo.Region() if enabled else None)

    def start_socket_server(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        self._server_thread = threading.Thread(
            target=self.socket_server_worker, name="overlay-socket", daemon=True
        )
        self._server_thread.start()

    def socket_server_worker(self) -> None:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
            self.socket_path.chmod(0o600)
            server.listen(8)
            server.settimeout(0.5)
            LOGGER.info("overlay socket listening path=%s", self.socket_path)
            while not self._server_stop.is_set():
                try:
                    client, _addr = server.accept()
                except TimeoutError:
                    continue
                with client:
                    payload = client.recv(256 * 1024)
                    if not payload:
                        continue
                    for line in payload.splitlines():
                        try:
                            command = json.loads(line.decode("utf-8"))
                        except json.JSONDecodeError as exc:
                            LOGGER.warning("invalid command: %s", exc)
                            continue
                        # GTK widgets must be updated on the main loop, not from
                        # the socket thread that receives backend state changes.
                        GLib.idle_add(self.apply_command, command)
        finally:
            server.close()
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass

    def apply_command(self, command: dict[str, Any]) -> bool:
        command_type = command.get("type")
        if command_type == "quit":
            Gtk.main_quit()
            return False
        if command_type != "state":
            return False

        self.state = command
        self.visible_overlay = bool(command.get("visible"))
        toast = command.get("toast")
        if self.visible_overlay:
            self.toast = None
        elif isinstance(toast, dict) and toast.get("text"):
            self.start_toast(toast)
        self.resize_to_monitor()
        # Toasts are display-only: input keeps passing through to the game.
        self.set_input_passthrough(not self.visible_overlay)
        self.set_gamescope_overlay_atoms(self.visible_overlay or self.toast is not None)
        if self.visible_overlay:
            self.show_all()
            self.present()
        elif self.toast is not None:
            # show() without present() so the game keeps focus.
            self.show_all()
        else:
            self.hide()
        self.queue_draw()
        return False

    def start_toast(self, toast: dict[str, Any]) -> None:
        self.toast = toast
        self._toast_token += 1
        token = self._toast_token
        GLib.timeout_add(int(TOAST_SECONDS * 1000), self.expire_toast, token)

    def expire_toast(self, token: int) -> bool:
        if token != self._toast_token or self.toast is None:
            return False
        self.toast = None
        if not self.visible_overlay:
            self.set_gamescope_overlay_atoms(False)
            self.hide()
        return False

    def on_button_press(self, _widget: Gtk.Widget, event: Any) -> bool:
        if not self.visible_overlay:
            return False
        if getattr(event, "type", None) != Gdk.EventType.BUTTON_PRESS:
            # Ignore the extra double/triple-click events GTK adds after a press.
            return True
        if int(getattr(event, "button", 0) or 0) != 1:
            return True
        return self.handle_pointer_press(float(event.x), float(event.y))

    def on_touch_event(self, _widget: Gtk.Widget, event: Any) -> bool:
        if not self.visible_overlay:
            return False
        # Only the initial contact counts, so sliding a finger across the grid
        # cannot fire every tile it passes over.
        if getattr(event, "type", None) != Gdk.EventType.TOUCH_BEGIN:
            return True
        return self.handle_pointer_press(float(event.x), float(event.y))

    def handle_pointer_press(self, x: float, y: float) -> bool:
        width, height = self.get_size()
        sounds = [
            sound for sound in self.state.get("sounds", []) if isinstance(sound, dict)
        ]
        target, index = hit_test(
            overlay_layout(width, height), x, y, len(sounds), self._tab_rects
        )
        if target == HIT_TAB and index is not None:
            self.send_action({"type": "tab", "index": index})
        elif target == HIT_OUTSIDE:
            self.send_action({"type": "input", "action": "hide"})
        elif target == HIT_TILE and index is not None:
            now = time.monotonic()
            if (
                index == self._last_pointer_action_index
                and now - self._last_pointer_action_at < POINTER_REPEAT_SECONDS
            ):
                return True
            self._last_pointer_action_index = index
            self._last_pointer_action_at = now
            self.state["selected_index"] = index
            self.queue_draw()
            self.send_action({"type": "select", "index": index, "play": True})
        return True

    def send_action(self, command: dict[str, Any]) -> None:
        if self.actions_socket_path is None:
            return
        encoded = (json.dumps(command, ensure_ascii=True) + "\n").encode("utf-8")
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.settimeout(0.2)
                client.connect(str(self.actions_socket_path))
                client.sendall(encoded)
            finally:
                client.close()
        except OSError as exc:
            LOGGER.warning(
                "action socket send failed path=%s error=%s",
                self.actions_socket_path,
                exc,
            )

    def on_destroy(self, *_args: Any) -> None:
        self._server_stop.set()
        self.set_gamescope_overlay_atoms(False)

    def get_xid(self) -> int | None:
        gdk_window = self.get_window()
        if gdk_window is None:
            return None
        get_xid = getattr(gdk_window, "get_xid", None)
        if callable(get_xid):
            return int(get_xid())
        return None

    def set_gamescope_overlay_atoms(self, enabled: bool) -> None:
        if enabled == self.xatoms_enabled:
            return
        self.xatoms_enabled = enabled
        xid = self.get_xid()
        if xid is None:
            LOGGER.warning("cannot set overlay atom: missing XID")
            return
        value = 1 if enabled else 0
        for atom in GAMESCOPE_OVERLAY_ATOMS:
            # Gamescope checks these X atoms to treat the popup as an external
            # overlay instead of a regular desktop window.
            if self.xatom_setter.set_cardinal(xid, atom, value):
                LOGGER.info("set %s=%s xid=%s", atom, value, xid)

    def on_draw(self, _widget: Gtk.Widget, context: cairo.Context) -> bool:
        width, height = self.get_size()
        if self.visible_overlay:
            self._tab_rects = render_overlay(context, width, height, self.state)
        elif self.toast is not None:
            render_toast(context, width, height, self.toast)
        return False


def render_overlay(
    context: cairo.Context,
    width: float,
    height: float,
    state: dict[str, Any],
) -> list[tuple[Rect, int]]:
    """Paint the full overlay and return the tab hit areas for touch input."""

    layout = overlay_layout(width, height)
    clear(context)
    fill_rect(context, Rect(0, 0, width, height), BACKDROP)
    fill_rect(context, layout.header, PANEL)
    fill_rect(context, layout.footer, PANEL)
    draw_line(context, 0, layout.header.bottom, width, layout.header.bottom, DIVIDER)
    draw_line(context, 0, layout.footer.y, width, layout.footer.y, DIVIDER)

    tab_rects = draw_header(context, layout, state)
    sounds = [sound for sound in state.get("sounds", []) if isinstance(sound, dict)]
    if sounds:
        draw_tiles(context, layout, state, sounds)
    else:
        draw_empty_state(context, layout, state)
    draw_footer(context, layout, state)
    return tab_rects


def draw_header(
    context: cairo.Context, layout: OverlayLayout, state: dict[str, Any]
) -> list[tuple[Rect, int]]:
    padding = layout.padding
    title_center_y = layout.tab_bar.y / 2 + 2
    title_width, _ = draw_text(
        context,
        "DeckSoundpad",
        padding,
        title_center_y,
        22,
        TEXT_PRIMARY,
        bold=True,
        valign="middle",
    )

    mic = state.get("mic") if isinstance(state.get("mic"), dict) else {}
    mic_label = str(mic.get("label") or "")
    if mic_label:
        draw_status_pill(
            context,
            mic_label,
            str(mic.get("tone") or "warn"),
            padding + title_width + 16,
            title_center_y,
            max_width=max(80.0, layout.width * 0.36),
        )

    page = int_value(state.get("page"))
    page_count = max(1, int_value(state.get("page_count"), 1))
    if page_count > 1:
        draw_page_indicator(
            context, page, page_count, layout.width - padding, title_center_y
        )

    tabs = [tab for tab in state.get("tabs", []) if isinstance(tab, dict)]
    return draw_tab_bar(
        context, layout.tab_bar, tabs, int_value(state.get("tab_index"))
    )


def draw_status_pill(
    context: cairo.Context,
    label: str,
    tone: str,
    x: float,
    center_y: float,
    *,
    max_width: float,
) -> None:
    color = TONE_COLORS.get(tone, TONE_COLORS["warn"])
    dot = 8
    text_width, _ = measure_text(context, label, 14, max_width=max_width)
    pill = Rect(x, center_y - 13, text_width + dot + 30, 26)
    rounded_rect(context, pill, 13)
    set_color(context, color, alpha_scale=0.16)
    context.fill_preserve()
    set_color(context, color, alpha_scale=0.55)
    context.set_line_width(1.0)
    context.stroke()
    context.arc(pill.x + 12 + dot / 2, center_y, dot / 2, 0, math.tau)
    set_color(context, color)
    context.fill()
    draw_text(
        context,
        label,
        pill.x + 12 + dot + 8,
        center_y,
        14,
        TEXT_PRIMARY,
        max_width=max_width,
        valign="middle",
    )


def draw_page_indicator(
    context: cairo.Context, page: int, page_count: int, right_x: float, center_y: float
) -> None:
    label = f"Page {page + 1} of {page_count}"
    label_width, _ = draw_text(
        context,
        label,
        right_x,
        center_y,
        14,
        TEXT_SECONDARY,
        align="right",
        valign="middle",
    )
    if page_count > 12:
        return
    dot, gap = 7.0, 6.0
    x = right_x - label_width - 14 - page_count * (dot + gap) + gap
    for index in range(page_count):
        context.arc(x + dot / 2, center_y, dot / 2, 0, math.tau)
        set_color(context, TEXT_PRIMARY, alpha_scale=1.0 if index == page else 0.32)
        context.fill()
        x += dot + gap


def draw_tab_bar(
    context: cairo.Context,
    bar: Rect,
    tabs: Sequence[dict[str, Any]],
    current: int,
) -> list[tuple[Rect, int]]:
    if not tabs:
        return []
    current = max(0, min(current, len(tabs) - 1))
    labels = [str(tab.get("label") or "Sounds") for tab in tabs]
    counts = [str(int_value(tab.get("count"))) for tab in tabs]
    max_label = max(120.0, bar.width * 0.3)
    widths = [
        measure_text(context, label, 16, bold=True, max_width=max_label)[0]
        + measure_text(context, count, 13)[0]
        + TAB_PADDING * 2
        + 8
        for label, count in zip(labels, counts)
    ]
    chevron_space = 22.0
    start, end = visible_tab_range(widths, current, bar.width, TAB_GAP)
    if (start, end) != (0, len(tabs)):
        start, end = visible_tab_range(
            widths, current, bar.width - chevron_space * 2, TAB_GAP
        )

    rects: list[tuple[Rect, int]] = []
    x = bar.x + (chevron_space if start > 0 else 0)
    center_y = bar.y + bar.height / 2
    if start > 0:
        draw_chevron(context, bar.x + 6, center_y, -1)
    for index in range(start, end):
        rect = Rect(x, bar.y, widths[index], bar.height)
        selected = index == current
        rounded_rect(context, rect, bar.height / 2)
        if selected:
            set_color(context, GLYPH_FILL)
            context.fill()
        else:
            set_color(context, TAB_FILL)
            context.fill_preserve()
            set_color(context, TAB_BORDER)
            context.set_line_width(1.0)
            context.stroke()
        label_width, _ = draw_text(
            context,
            labels[index],
            rect.x + TAB_PADDING,
            center_y,
            16,
            TEXT_ON_LIGHT if selected else TEXT_SECONDARY,
            bold=True,
            max_width=max_label,
            valign="middle",
        )
        draw_text(
            context,
            counts[index],
            rect.x + TAB_PADDING + label_width + 8,
            center_y,
            13,
            TEXT_ON_LIGHT_MUTED if selected else TEXT_MUTED,
            valign="middle",
        )
        rects.append((rect, index))
        x += widths[index] + TAB_GAP
    if end < len(tabs):
        draw_chevron(context, x - TAB_GAP + 10, center_y, 1)
    return rects


def draw_chevron(
    context: cairo.Context, x: float, center_y: float, direction: int
) -> None:
    size = 6
    context.move_to(x + (size if direction < 0 else 0), center_y - size)
    context.line_to(x + (0 if direction < 0 else size), center_y)
    context.line_to(x + (size if direction < 0 else 0), center_y + size)
    set_color(context, TEXT_SECONDARY)
    context.set_line_width(2.0)
    context.stroke()


def draw_tiles(
    context: cairo.Context,
    layout: OverlayLayout,
    state: dict[str, Any],
    sounds: Sequence[dict[str, Any]],
) -> None:
    selected_index = int_value(state.get("selected_index"))
    playing_ids = {
        sound_id
        for sound_id in state.get("playing_ids", [])
        if isinstance(sound_id, str)
    }
    selected_rect: Rect | None = None

    for index, sound in enumerate(sounds[:SOUNDS_PER_PAGE]):
        rect = layout.tile_rect(index)
        selected = index == selected_index
        playing = sound.get("id") in playing_ids
        rounded_rect(context, rect, TILE_RADIUS)
        if selected:
            set_color(context, TILE_SELECTED_FILL)
            context.fill()
            selected_rect = rect
        else:
            set_color(context, TILE_FILL)
            context.fill_preserve()
            set_color(context, TILE_BORDER)
            context.set_line_width(1.0)
            context.stroke()

        right_inset = TILE_TEXT_INSET
        if playing:
            draw_playing_marker(context, rect)
            right_inset += 18
        label = str(sound.get("display_name") or sound.get("relative_path") or "Sound")
        max_width = max(20.0, rect.width - TILE_TEXT_INSET - right_inset)
        draw_text(
            context,
            label,
            rect.x + TILE_TEXT_INSET,
            rect.y + rect.height / 2,
            17,
            TEXT_PRIMARY,
            bold=selected,
            max_width=max_width,
            max_lines=2,
            valign="middle",
        )

    if selected_rect is not None:
        # Drawn last and outside the tile so neighbours never cover the ring.
        ring = Rect(
            selected_rect.x - 3,
            selected_rect.y - 3,
            selected_rect.width + 6,
            selected_rect.height + 6,
        )
        rounded_rect(context, ring, TILE_RADIUS + 3)
        set_color(context, FOCUS_RING)
        context.set_line_width(3.0)
        context.stroke()


def draw_playing_marker(context: cairo.Context, tile: Rect) -> None:
    # Accent bar on the left edge plus three equalizer bars in the corner.
    context.save()
    rounded_rect(context, tile, TILE_RADIUS)
    context.clip()
    context.rectangle(tile.x, tile.y, 4, tile.height)
    set_color(context, PLAYING)
    context.fill()
    context.restore()
    bar_width, gap = 3.0, 2.0
    base_y = tile.y + 22
    x = tile.right - 12 - (bar_width * 3 + gap * 2)
    for bar_height in (8, 13, 10):
        context.rectangle(x, base_y - bar_height, bar_width, bar_height)
        x += bar_width + gap
    set_color(context, PLAYING)
    context.fill()


def draw_empty_state(
    context: cairo.Context, layout: OverlayLayout, state: dict[str, Any]
) -> None:
    folder = str(state.get("library_dir") or "~/Music/DeckSoundpad")
    max_width = layout.grid.width * 0.8
    center_x = layout.grid.x + layout.grid.width / 2
    y = layout.grid.y + layout.grid.height * 0.32
    _, height = draw_text(
        context,
        "No sounds yet",
        center_x,
        y,
        26,
        TEXT_PRIMARY,
        bold=True,
        align="center",
        max_width=max_width,
    )
    y += height + 12
    _, height = draw_text(
        context,
        f"Add WAV, FLAC, OGG, or MP3 files to {folder}.",
        center_x,
        y,
        17,
        TEXT_SECONDARY,
        align="center",
        max_width=max_width,
        max_lines=2,
    )
    y += height + 8
    draw_text(
        context,
        "Then open Decky, select Refresh sounds, and pick DeckSoundpad mic in your voice app.",
        center_x,
        y,
        15,
        TEXT_MUTED,
        align="center",
        max_width=max_width,
        max_lines=2,
    )


def legend_items(state: dict[str, Any]) -> list[tuple[list[str], str]]:
    hotkey = str(state.get("overlay_hotkey_button") or "L5").upper()
    if hotkey not in {"L4", "L5", "R4", "R5"}:
        hotkey = "L5"
    items: list[tuple[list[str], str]] = [
        (["A"], "Play"),
        (["X"], "Play & stay"),
        (["Y"], "Stop all"),
        (["B", hotkey], "Close"),
        (["L1", "R1"], "Page"),
    ]
    replay = state.get("replay_button")
    if isinstance(replay, str) and replay:
        items.append(([replay.upper()], "Replay last"))
    return items


def draw_footer(
    context: cairo.Context, layout: OverlayLayout, state: dict[str, Any]
) -> None:
    padding = layout.padding
    center_y = layout.footer.y + layout.footer.height / 2
    items = legend_items(state)
    widths = [legend_item_width(context, glyphs, label) for glyphs, label in items]
    item_gap = 18.0
    min_message_width = min(320.0, layout.width * 0.3)
    available = layout.width - padding * 2 - min_message_width
    # Drop the least essential hints (listed last) on narrow screens.
    while len(items) > 2 and sum(widths) + item_gap * (len(items) - 1) > available:
        items.pop()
        widths.pop()
    legend_width = sum(widths) + item_gap * (len(items) - 1)
    x = layout.width - padding - legend_width
    for (glyphs, label), width in zip(items, widths):
        draw_legend_item(context, glyphs, label, x, center_y)
        x += width + item_gap

    message_width = max(40.0, layout.width - padding * 3 - legend_width)
    message = str(state.get("message") or "")
    if message and state.get("message_tone") == "error":
        draw_tone_icon(context, "error", padding + 11, center_y, 11)
        draw_text(
            context,
            message,
            padding + 30,
            center_y,
            15,
            TONE_COLORS["error"],
            max_width=message_width - 30,
            valign="middle",
        )
    elif message:
        draw_text(
            context,
            message,
            padding,
            center_y,
            15,
            TEXT_PRIMARY,
            max_width=message_width,
            valign="middle",
        )
    else:
        total = int_value(state.get("total_count"))
        summary = f"{total} sound" + ("" if total == 1 else "s")
        draw_text(
            context,
            summary,
            padding,
            center_y,
            14,
            TEXT_MUTED,
            max_width=message_width,
            valign="middle",
        )


def legend_item_width(
    context: cairo.Context, glyphs: Sequence[str], label: str
) -> float:
    glyph_widths = sum(glyph_width(context, glyph) for glyph in glyphs) + 4 * (
        len(glyphs) - 1
    )
    return glyph_widths + 7 + measure_text(context, label, 14)[0]


def draw_legend_item(
    context: cairo.Context, glyphs: Sequence[str], label: str, x: float, center_y: float
) -> None:
    for glyph in glyphs:
        x += draw_button_glyph(context, glyph, x, center_y) + 4
    draw_text(context, label, x + 3, center_y, 14, TEXT_SECONDARY, valign="middle")


def glyph_width(context: cairo.Context, label: str) -> float:
    if label in FACE_BUTTONS:
        return 24.0
    return measure_text(context, label, 12, bold=True)[0] + 14


def draw_button_glyph(
    context: cairo.Context, label: str, x: float, center_y: float
) -> float:
    """Draw a Steam-style button glyph: circles for face buttons, pills otherwise."""

    width = glyph_width(context, label)
    if label in FACE_BUTTONS:
        context.arc(x + width / 2, center_y, width / 2, 0, math.tau)
        size = 13
    else:
        rounded_rect(context, Rect(x, center_y - 11, width, 22), 6)
        size = 12
    set_color(context, GLYPH_FILL)
    context.fill()
    draw_text(
        context,
        label,
        x + width / 2,
        center_y,
        size,
        TEXT_ON_LIGHT,
        bold=True,
        align="center",
        valign="middle",
    )
    return width


def draw_tone_icon(
    context: cairo.Context, tone: str, center_x: float, center_y: float, radius: float
) -> None:
    context.arc(center_x, center_y, radius, 0, math.tau)
    set_color(context, TONE_COLORS.get(tone, TONE_COLORS["info"]))
    context.fill()
    set_color(context, TEXT_ON_LIGHT)
    if tone == "play":
        size = radius * 0.62
        context.move_to(center_x - size * 0.6, center_y - size)
        context.line_to(center_x + size, center_y)
        context.line_to(center_x - size * 0.6, center_y + size)
        context.close_path()
        context.fill()
        return
    glyph = "!" if tone == "error" else "i"
    draw_text(
        context,
        glyph,
        center_x,
        center_y,
        int(radius * 1.3),
        TEXT_ON_LIGHT,
        bold=True,
        align="center",
        valign="middle",
    )


def render_toast(
    context: cairo.Context, width: float, height: float, toast: dict[str, Any]
) -> None:
    """Paint the short confirmation shown after the overlay closes."""

    clear(context)
    tone = str(toast.get("tone") or "info")
    text = str(toast.get("text") or "")
    max_text_width = width * 0.6
    text_width, _ = measure_text(
        context, text, 18, bold=tone == "play", max_width=max_text_width
    )
    icon_radius = 13.0
    pill_width = 16 + icon_radius * 2 + 12 + text_width + 22
    pill = Rect((width - pill_width) / 2, height - 52 - 40, pill_width, 52)
    rounded_rect(context, pill, 26)
    set_color(context, TOAST_FILL)
    context.fill_preserve()
    set_color(context, TAB_BORDER)
    context.set_line_width(1.0)
    context.stroke()
    center_y = pill.y + pill.height / 2
    draw_tone_icon(context, tone, pill.x + 16 + icon_radius, center_y, icon_radius)
    draw_text(
        context,
        text,
        pill.x + 16 + icon_radius * 2 + 12,
        center_y,
        18,
        TEXT_PRIMARY,
        bold=tone == "play",
        max_width=max_text_width,
        valign="middle",
    )


def clear(context: cairo.Context) -> None:
    context.set_operator(cairo.OPERATOR_SOURCE)
    context.set_source_rgba(0, 0, 0, 0)
    context.paint()
    context.set_operator(cairo.OPERATOR_OVER)


def set_color(
    context: cairo.Context, color: Color, *, alpha_scale: float = 1.0
) -> None:
    red, green, blue, alpha = color
    context.set_source_rgba(red, green, blue, min(1.0, alpha * alpha_scale))


def fill_rect(context: cairo.Context, rect: Rect, color: Color) -> None:
    context.rectangle(rect.x, rect.y, rect.width, rect.height)
    set_color(context, color)
    context.fill()


def draw_line(
    context: cairo.Context, x1: float, y1: float, x2: float, y2: float, color: Color
) -> None:
    context.move_to(x1, y1)
    context.line_to(x2, y2)
    set_color(context, color)
    context.set_line_width(1.0)
    context.stroke()


def rounded_rect(context: cairo.Context, rect: Rect, radius: float) -> None:
    radius = min(radius, rect.width / 2, rect.height / 2)
    x, y, width, height = rect.x, rect.y, rect.width, rect.height
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    context.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    context.close_path()


def draw_text(
    context: cairo.Context,
    text: str,
    x: float,
    y: float,
    size: int,
    color: Color,
    *,
    bold: bool = False,
    max_width: float | None = None,
    max_lines: int = 1,
    align: str = "left",
    valign: str = "top",
) -> tuple[float, float]:
    """Draw text anchored at (x, y) and return its drawn (width, height).

    ``align`` picks the horizontal anchor (left, center, right) and ``valign``
    the vertical one (top or middle). Text wider than ``max_width`` wraps up to
    ``max_lines`` lines and ends with an ellipsis.
    """

    if PangoCairo is not None:
        layout = pango_layout(context, text, size, bold, max_width, max_lines)
        width, height = layout.get_pixel_size()
        context.move_to(
            anchor_x(x, width, align), y - (height / 2 if valign == "middle" else 0)
        )
        set_color(context, color)
        PangoCairo.show_layout(context, layout)
        return float(width), float(height)

    select_toy_font(context, size, bold)
    if max_width is not None:
        text = fit_toy_text(context, text, max_width)
    width = toy_text_width(context, text)
    ascent, descent = context.font_extents()[:2]
    height = ascent + descent
    top = y - (height / 2 if valign == "middle" else 0)
    context.move_to(anchor_x(x, width, align), top + ascent)
    set_color(context, color)
    context.show_text(text)
    return width, height


def measure_text(
    context: cairo.Context,
    text: str,
    size: int,
    *,
    bold: bool = False,
    max_width: float | None = None,
    max_lines: int = 1,
) -> tuple[float, float]:
    if PangoCairo is not None:
        width, height = pango_layout(
            context, text, size, bold, max_width, max_lines
        ).get_pixel_size()
        return float(width), float(height)
    select_toy_font(context, size, bold)
    if max_width is not None:
        text = fit_toy_text(context, text, max_width)
    ascent, descent = context.font_extents()[:2]
    return toy_text_width(context, text), ascent + descent


def anchor_x(x: float, width: float, align: str) -> float:
    if align == "center":
        return x - width / 2
    if align == "right":
        return x - width
    return x


def pango_layout(
    context: cairo.Context,
    text: str,
    size: int,
    bold: bool,
    max_width: float | None,
    max_lines: int,
) -> Any:
    layout = PangoCairo.create_layout(context)
    font = Pango.FontDescription.from_string(FONT_FAMILY)
    font.set_absolute_size(size * Pango.SCALE)
    font.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
    layout.set_font_description(font)
    layout.set_single_paragraph_mode(True)
    layout.set_text(text, -1)
    if max_width is not None:
        layout.set_width(int(max_width * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        if max_lines > 1:
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            # A negative height limits the layout to that many lines.
            layout.set_height(-max_lines)
    return layout


def select_toy_font(context: cairo.Context, size: int, bold: bool) -> None:
    context.select_font_face(
        FONT_FAMILY,
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
    )
    context.set_font_size(size)


def toy_text_width(context: cairo.Context, text: str) -> float:
    extents = context.text_extents(text)
    return float(getattr(extents, "x_advance", extents[4]))


def fit_toy_text(context: cairo.Context, text: str, max_width: float) -> str:
    if toy_text_width(context, text) <= max_width:
        return text
    ellipsis = "..."
    low, high = 0, len(text)
    # Binary search for the longest prefix that fits next to the ellipsis.
    while low < high:
        middle = (low + high + 1) // 2
        if toy_text_width(context, text[:middle].rstrip() + ellipsis) <= max_width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ellipsis


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DeckSoundpad external gamescope overlay"
    )
    parser.add_argument("--socket", required=True)
    parser.add_argument("--actions-socket")
    parser.add_argument("--log")
    return parser.parse_args()


def configure_environment() -> None:
    os.environ.setdefault("GDK_BACKEND", "x11")
    os.environ.setdefault("DISPLAY", ":0")
    if "GAMESCOPE_WAYLAND_DISPLAY" in os.environ:
        # The overlay path depends on X11 window atoms, so do not let GTK switch
        # to Wayland just because Gamescope exported a Wayland display.
        os.environ.pop("WAYLAND_DISPLAY", None)


def main() -> int:
    configure_environment()
    args = parse_args()
    configure_logging(args.log)
    LOGGER.info(
        "starting external overlay display=%s gdk=%s pango=%s",
        os.environ.get("DISPLAY"),
        os.environ.get("GDK_BACKEND"),
        PangoCairo is not None,
    )
    actions_socket_path = Path(args.actions_socket) if args.actions_socket else None
    OverlayWindow(Path(args.socket), actions_socket_path)
    Gtk.main()
    return 0


def configure_logging(log_path: str | None) -> None:
    logging_kwargs = {
        "level": logging.INFO,
        "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
    }
    if not log_path:
        logging.basicConfig(**logging_kwargs)
        return

    try:
        logging.basicConfig(filename=log_path, **logging_kwargs)
    except OSError as exc:
        logging.basicConfig(**logging_kwargs)
        LOGGER.warning("file logging unavailable path=%s error=%s", log_path, exc)


if __name__ == "__main__":
    raise SystemExit(main())
