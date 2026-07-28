from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
import threading
import time
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

LOGGER = logging.getLogger("decksoundpad.external_overlay")
GAMESCOPE_OVERLAY_ATOMS = ("GAMESCOPE_EXTERNAL_OVERLAY", "STEAM_EXTERNAL_OVERLAY")
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
GRID_COLUMNS = 5
GRID_ROWS = 7
GRID_GAP = 10
OVERLAY_PADDING = 32
OVERLAY_HEADER_HEIGHT = 118
OVERLAY_FOOTER_HEIGHT = 52
OVERLAY_BACKGROUND_ALPHA = 0.58
OVERLAY_DIVIDER_ALPHA = 0.38
OVERLAY_TILE_ALPHA = 0.54
OVERLAY_SELECTED_TILE_ALPHA = 0.72
OVERLAY_SELECTED_BORDER_ALPHA = 0.82
OVERLAY_TILE_BORDER_ALPHA = 0.14


class XAtomSetter:
    def __init__(self) -> None:
        self._lib = None
        try:
            self._lib = ctypes.cdll.LoadLibrary("libX11.so.6")
            self._lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self._lib.XOpenDisplay.restype = ctypes.c_void_p
            self._lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
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
        display = self._lib.XOpenDisplay(display_name.encode("utf-8") if display_name else None)
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
            "message": "DeckSoundpad",
        }
        self.xatoms_enabled = False
        self.xatom_setter = XAtomSetter()
        self._server_thread: threading.Thread | None = None
        self._server_stop = threading.Event()
        self._last_pointer_action_at = 0.0
        self._last_pointer_action_index = -1

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
        monitor = display.get_monitor(0) if display and display.get_n_monitors() else None
        if monitor:
            geometry = monitor.get_geometry()
            self.move(geometry.x, geometry.y)
            self.resize(geometry.width, geometry.height)
            return
        self.move(0, 0)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def set_input_passthrough(self, enabled: bool) -> None:
        width, height = self.get_size()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, width), max(1, height))
        context = cairo.Context(surface)
        alpha = 0 if enabled else 1
        context.set_source_rgba(0, 0, 0, alpha)
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.paint()
        region = Gdk.cairo_region_create_from_surface(surface)
        # An empty input shape lets games receive clicks while the hidden overlay
        # window remains alive above them.
        self.input_shape_combine_region(region)

    def start_socket_server(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        self._server_thread = threading.Thread(target=self.socket_server_worker, name="overlay-socket", daemon=True)
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
                except socket.timeout:
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
        self.resize_to_monitor()
        self.set_input_passthrough(not self.visible_overlay)
        self.set_gamescope_overlay_atoms(self.visible_overlay)
        if self.visible_overlay:
            self.show_all()
            self.present()
        else:
            self.hide()
        self.queue_draw()
        return False

    def on_button_press(self, _widget: Gtk.Widget, event: Any) -> bool:
        if not self.visible_overlay:
            return False
        if int(getattr(event, "button", 0) or 0) != 1:
            return True
        return self.handle_pointer_press(float(event.x), float(event.y))

    def on_touch_event(self, _widget: Gtk.Widget, event: Any) -> bool:
        if not self.visible_overlay:
            return False
        event_type = getattr(event, "type", None)
        if event_type not in (Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.TOUCH_UPDATE):
            return True
        return self.handle_pointer_press(float(event.x), float(event.y))

    def handle_pointer_press(self, x: float, y: float) -> bool:
        index = self.sound_index_at(x, y)
        if index is None:
            return True

        now = time.monotonic()
        if index == self._last_pointer_action_index and now - self._last_pointer_action_at < 0.25:
            return True
        self._last_pointer_action_index = index
        self._last_pointer_action_at = now

        self.state["selected_index"] = index
        self.queue_draw()
        self.send_action({"type": "select", "index": index, "play": True})
        return True

    def sound_index_at(self, x: float, y: float) -> int | None:
        sounds = [sound for sound in self.state.get("sounds", []) if isinstance(sound, dict)]
        if not sounds:
            return None
        width, height = self.get_size()
        layout = overlay_layout(width, height)
        grid_x = layout["grid_x"]
        grid_y = layout["grid_y"]
        cell_width = layout["cell_width"]
        cell_height = layout["cell_height"]
        for index in range(min(len(sounds), GRID_COLUMNS * GRID_ROWS)):
            col = index % GRID_COLUMNS
            row = index // GRID_COLUMNS
            cell_x = grid_x + col * (cell_width + GRID_GAP)
            cell_y = grid_y + row * (cell_height + GRID_GAP)
            if cell_x <= x <= cell_x + cell_width and cell_y <= y <= cell_y + cell_height:
                return index
        return None

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
            LOGGER.warning("action socket send failed path=%s error=%s", self.actions_socket_path, exc)

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
        if not self.visible_overlay:
            return False

        width, height = self.get_size()
        sounds = [sound for sound in self.state.get("sounds", []) if isinstance(sound, dict)]
        selected_index = int(self.state.get("selected_index") or 0)
        page = int(self.state.get("page") or 0)
        page_count = int(self.state.get("page_count") or 1)
        total_count = int(self.state.get("total_count") or len(sounds))
        message = str(self.state.get("message") or "DeckSoundpad")
        overlay_hotkey_button = str(self.state.get("overlay_hotkey_button") or "L5").upper()
        if overlay_hotkey_button not in {"L4", "L5", "R4", "R5"}:
            overlay_hotkey_button = "L5"

        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)

        layout = overlay_layout(width, height)
        padding = layout["padding"]

        context.rectangle(0, 0, width, height)
        context.set_source_rgba(0.03, 0.04, 0.05, OVERLAY_BACKGROUND_ALPHA)
        context.fill()

        context.set_source_rgba(0.30, 0.72, 0.82, OVERLAY_DIVIDER_ALPHA)
        context.set_line_width(1.2)
        context.move_to(padding, layout["grid_y"] - 18)
        context.line_to(width - padding, layout["grid_y"] - 18)
        context.stroke()

        draw_text(context, "DeckSoundpad", padding, 38, 27, (0.95, 0.98, 1.0, 1.0), bold=True)
        draw_text(context, ellipsize(message, 56), padding, 64, 15, (0.70, 0.78, 0.82, 1.0))
        draw_text(
            context,
            f"{total_count} sounds loaded",
            padding,
            88,
            13,
            (0.58, 0.66, 0.70, 1.0),
        )
        draw_control_chips(
            context,
            [
                (overlay_hotkey_button, "close"),
                ("D-pad", "move"),
                ("A", "play"),
                ("L1/R1", "page"),
                ("Touch", "play tile"),
            ],
            width - padding,
            28,
            padding + min(430, width * 0.38),
        )
        draw_text(
            context,
            f"Page {page + 1} / {page_count}",
            width - padding - 118,
            92,
            15,
            (0.70, 0.78, 0.82, 1.0),
        )

        grid_x = layout["grid_x"]
        grid_y = layout["grid_y"]
        cell_width = layout["cell_width"]
        cell_height = layout["cell_height"]

        if not sounds:
            draw_text(context, "No sounds found", grid_x, grid_y + 92, 24, (0.95, 0.98, 1.0, 1.0), bold=True)
            draw_text(
                context,
                "Add WAV, FLAC, OGG, or MP3 files to ~/Music/DeckSoundpad.",
                grid_x,
                grid_y + 128,
                17,
                (0.70, 0.78, 0.82, 1.0),
            )
            draw_text(
                context,
                "Then open Decky, refresh sounds, and select DeckSoundpad mic in voice chat.",
                grid_x,
                grid_y + 154,
                15,
                (0.58, 0.66, 0.70, 1.0),
            )
            return False

        for index, sound in enumerate(sounds[: GRID_COLUMNS * GRID_ROWS]):
            col = index % GRID_COLUMNS
            row = index // GRID_COLUMNS
            cell_x = grid_x + col * (cell_width + GRID_GAP)
            cell_y = grid_y + row * (cell_height + GRID_GAP)
            selected = index == selected_index

            if selected:
                context.set_source_rgba(0.10, 0.43, 0.50, OVERLAY_SELECTED_TILE_ALPHA)
            else:
                context.set_source_rgba(0.10, 0.12, 0.14, OVERLAY_TILE_ALPHA)
            rounded_rect(context, cell_x, cell_y, cell_width, cell_height, 8)
            context.fill()

            border_alpha = OVERLAY_SELECTED_BORDER_ALPHA if selected else OVERLAY_TILE_BORDER_ALPHA
            context.set_source_rgba(0.30, 0.72, 0.82, border_alpha)
            context.set_line_width(1.6 if selected else 1.0)
            rounded_rect(context, cell_x + 0.8, cell_y + 0.8, cell_width - 1.6, cell_height - 1.6, 8)
            context.stroke()

            label = str(sound.get("display_name") or sound.get("relative_path") or "Sound")
            item_number = page * GRID_COLUMNS * GRID_ROWS + index + 1
            combined_label = f"{item_number}. {label}"
            max_label_chars = max(10, int((cell_width - 28) / 8))
            draw_text(
                context,
                ellipsize(combined_label, max_label_chars),
                cell_x + 14,
                cell_y + max(31, cell_height * 0.56),
                17,
                (0.96, 0.98, 1.0, 1.0),
                bold=selected,
            )
        footer_y = layout["footer_y"]
        context.set_source_rgba(0.30, 0.72, 0.82, OVERLAY_DIVIDER_ALPHA)
        context.set_line_width(1.0)
        context.move_to(padding, footer_y - 12)
        context.line_to(width - padding, footer_y - 12)
        context.stroke()

        safe_selected_index = clamp_number(selected_index, 0, max(0, len(sounds) - 1))
        selected_sound = sounds[safe_selected_index] if sounds else {}
        selected_label = str(selected_sound.get("display_name") or selected_sound.get("relative_path") or "Sound")
        absolute_index = page * GRID_COLUMNS * GRID_ROWS + safe_selected_index + 1
        selected_summary = f"Selected {absolute_index}/{max(total_count, absolute_index)}: {selected_label}"
        draw_text(
            context,
            ellipsize(selected_summary, max(24, int((width - padding * 2) / 9))),
            padding,
            footer_y + 22,
            14,
            (0.88, 0.94, 0.96, 1.0),
        )
        draw_text(
            context,
            f"A plays and closes the overlay. {overlay_hotkey_button} closes without playing.",
            padding,
            footer_y + 43,
            12,
            (0.58, 0.66, 0.70, 1.0),
        )
        return False


def overlay_layout(width: int, height: int) -> dict[str, float]:
    padding = min(OVERLAY_PADDING, max(18, width * 0.035))
    header_height = min(OVERLAY_HEADER_HEIGHT, max(104, height * 0.15))
    footer_height = min(OVERLAY_FOOTER_HEIGHT, max(48, height * 0.065))
    grid_x = padding
    grid_y = header_height
    grid_width = max(1, width - padding * 2)
    grid_height = max(1, height - header_height - footer_height)
    cell_width = (grid_width - GRID_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS
    cell_height = (grid_height - GRID_GAP * (GRID_ROWS - 1)) / GRID_ROWS
    footer_y = height - footer_height
    return {
        "panel_width": width,
        "panel_height": height,
        "panel_x": 0,
        "panel_y": 0,
        "padding": padding,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "footer_y": footer_y,
    }


def rounded_rect(context: cairo.Context, x: float, y: float, width: float, height: float, radius: float) -> None:
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -1.5708, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
    context.arc(x + radius, y + height - radius, radius, 1.5708, 3.14159)
    context.arc(x + radius, y + radius, radius, 3.14159, 4.71239)
    context.close_path()


def draw_text(
    context: cairo.Context,
    text: str,
    x: float,
    y: float,
    size: int,
    color: tuple[float, float, float, float],
    *,
    bold: bool = False,
) -> None:
    context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    context.set_font_size(size)
    context.set_source_rgba(*color)
    context.move_to(x, y)
    context.show_text(text)


def draw_control_chips(
    context: cairo.Context,
    chips: list[tuple[str, str]],
    right_x: float,
    y: float,
    min_x: float,
) -> None:
    x = right_x
    row_y = y
    gap = 7
    for key, label in reversed(chips):
        key_width = text_width(context, key, 12, bold=True)
        label_width = text_width(context, label, 12)
        chip_width = key_width + label_width + 26
        if x - chip_width < min_x and x < right_x:
            x = right_x
            row_y += 26
        chip_x = x - chip_width
        rounded_rect(context, chip_x, row_y, chip_width, 21, 6)
        context.set_source_rgba(0.09, 0.12, 0.14, 0.72)
        context.fill()
        context.set_source_rgba(0.30, 0.72, 0.82, 0.26)
        context.set_line_width(1.0)
        rounded_rect(context, chip_x + 0.5, row_y + 0.5, chip_width - 1.0, 20, 6)
        context.stroke()
        draw_text(context, key, chip_x + 8, row_y + 15, 12, (0.95, 0.98, 1.0, 1.0), bold=True)
        draw_text(
            context,
            label,
            chip_x + key_width + 14,
            row_y + 15,
            12,
            (0.70, 0.78, 0.82, 1.0),
        )
        x = chip_x - gap


def text_width(context: cairo.Context, text: str, size: int, *, bold: bool = False) -> float:
    context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    context.set_font_size(size)
    extents = context.text_extents(text)
    return float(getattr(extents, "x_advance", extents[4]))


def clamp_number(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def ellipsize(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeckSoundpad external gamescope overlay")
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
    LOGGER.info("starting external overlay display=%s gdk=%s", os.environ.get("DISPLAY"), os.environ.get("GDK_BACKEND"))
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
