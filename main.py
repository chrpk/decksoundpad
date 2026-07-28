"""Decky bridge and external-overlay coordinator for DeckSoundpad."""

from __future__ import annotations

# The backend package is added to sys.path before its imports below. Keep that
# runtime setup close to the imports and document the intentional E402 exception.
# ruff: noqa: E402
import asyncio
import hashlib

try:
    import fcntl
except ImportError:  # pragma: no cover - SteamOS/Linux always has fcntl.
    fcntl = None  # type: ignore[assignment]
import json
import os
import pwd
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import decky
except ImportError:  # Local development fallback.
    import logging

    class _DeckyFallback:
        DECKY_PLUGIN_DIR = str(Path(__file__).resolve().parent)
        logger = logging.getLogger("decksoundpad.decky")

    decky = _DeckyFallback()  # type: ignore[assignment]


BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from decksoundpad import __version__
from decksoundpad.app import DeckSoundpadApp, start_healthcheck_loop
from decksoundpad.config import Settings, load_config
from decksoundpad.logging_setup import setup_logging
from decksoundpad.models import AudioStatus, LibraryStatus, PlayerStatus, Status
from decksoundpad.paths import ensure_app_dirs, resolve_paths, user_owner
from decksoundpad.process import decky_runtime_env, subprocess_user_kwargs
from decksoundpad.safe_files import (
    ensure_directory,
    open_regular_file,
    set_socket_metadata,
)

EV_KEY = 0x01
KEY_MAX = 0x2FF
BTN_GRIPL = 0x224
BTN_GRIPR = 0x225
BTN_GRIPL2 = 0x226
BTN_GRIPR2 = 0x227
BTN_SOUTH = 0x130
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
HOTKEY_DEBOUNCE_SECONDS = 0.45
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
    BTN_DPAD_UP: "up",
    BTN_DPAD_DOWN: "down",
    BTN_DPAD_LEFT: "left",
    BTN_DPAD_RIGHT: "right",
    BTN_TL: "page_prev",
    BTN_TR: "page_next",
}
HOTKEY_DIAGNOSTIC_PRESS_LIMIT = 80
EXTERNAL_OVERLAY_SOUNDS_PER_PAGE = 35
EXTERNAL_OVERLAY_GRID_COLUMNS = 5
EXTERNAL_OVERLAY_SOCKET_NAME = "external-overlay.sock"
EXTERNAL_OVERLAY_ACTION_SOCKET_NAME = "external-overlay-actions.sock"
EXTERNAL_OVERLAY_LOG_NAME = "external-overlay.log"
DIRECT_INPUT_TOGGLE_DEDUP_SECONDS = 0.55
FRONTEND_AFTER_DIRECT_DEDUP_SECONDS = 0.9
HIDRAW_ACTION_DEBOUNCE_SECONDS = 0.22
HIDRAW_STICK_NAVIGATION_THRESHOLD = 14500
HIDRAW_STICK_NAVIGATION_REPEAT_SECONDS = 0.24
STEAM_DECK_HID_REPORT_VERSION = 0x01
STEAM_DECK_HID_DECK_STATE_TYPE = 0x09
STEAM_DECK_LBUTTON_R = 0x00000004
STEAM_DECK_LBUTTON_L = 0x00000008
STEAM_DECK_LBUTTON_A = 0x00000080
STEAM_DECK_LBUTTON_DPAD_UP = 0x00000100
STEAM_DECK_LBUTTON_DPAD_RIGHT = 0x00000200
STEAM_DECK_LBUTTON_DPAD_LEFT = 0x00000400
STEAM_DECK_LBUTTON_DPAD_DOWN = 0x00000800
STEAM_DECK_LBUTTON_R5 = STEAM_DECK_REAR_BUTTON_MASKS["r5"]
STEAM_DECK_HID_DIRECT_SOURCES = {"os-input", "hidraw-input"}
STEAM_DECK_HID_ACTIONS = (
    (STEAM_DECK_LBUTTON_A, "play"),
    (STEAM_DECK_LBUTTON_DPAD_RIGHT, "right"),
    (STEAM_DECK_LBUTTON_DPAD_DOWN, "down"),
    (STEAM_DECK_LBUTTON_DPAD_LEFT, "left"),
    (STEAM_DECK_LBUTTON_DPAD_UP, "up"),
    (STEAM_DECK_LBUTTON_L, "page_prev"),
    (STEAM_DECK_LBUTTON_R, "page_next"),
)
EVIOCGRAB = 0x40044590
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


def normalize_overlay_hotkey_button(button: object) -> str:
    value = str(button or "").lower()
    return value if value in OVERLAY_HOTKEY_BUTTONS else "l5"


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


class Plugin:
    """Expose Decky callables and coordinate backend and overlay lifecycles."""

    async def _main(self) -> None:
        self.paths = resolve_paths(
            env=os.environ,
            plugin_dir=Path(getattr(decky, "DECKY_PLUGIN_DIR", Path(__file__).parent)),
        )
        ensure_app_dirs(self.paths)
        self.settings: Settings = load_config(self.paths)
        self.logger = setup_logging(self.paths)
        self._bridge_errors: list[str] = []
        self._backend_lock = threading.RLock()
        self._backend_start_thread: threading.Thread | None = None
        self._backend_start_completed = False
        self._bridge_lifecycle_lock = threading.RLock()
        self._unloading = False
        self._healthcheck_stop: threading.Event | None = None
        self._hotkey_stop = threading.Event()
        self._hotkey_thread: threading.Thread | None = None
        self._hidraw_stop = threading.Event()
        self._hidraw_thread: threading.Thread | None = None
        self._input_restart_thread: threading.Thread | None = None
        self._input_restart_requested = threading.Event()
        self._input_restart_request_lock = threading.Lock()
        self._input_monitor_lock = threading.RLock()
        self._input_restarts_disabled = False
        self._external_overlay_lock = threading.RLock()
        self._external_overlay_process: subprocess.Popen[Any] | None = None
        self._external_overlay_visible = False
        self._external_overlay_sounds: list[dict[str, Any]] = []
        self._external_overlay_page = 0
        self._external_overlay_selected_index = 0
        self._external_overlay_message = "Ready"
        self._external_overlay_last_direct_toggle = 0.0
        self._external_overlay_action_stop = threading.Event()
        self._external_overlay_action_thread: threading.Thread | None = None
        self._external_overlay_action_server_socket: socket.socket | None = None
        self._external_overlay_input_grab_handles: list[tuple[str, str, Any]] = []
        self._external_overlay_input_grab_attempted = False
        self._external_overlay_evdev_stop = threading.Event()
        self._external_overlay_evdev_thread: threading.Thread | None = None
        self._hidraw_action_last_at: dict[str, float] = {}
        self._hidraw_stick_direction: dict[str, str | None] = {}
        self._hidraw_stick_last_at: dict[str, float] = {}
        self.app = self._create_backend()
        self._start_healthcheck()
        self.logger.info("DeckSoundpad Decky bridge loaded")
        self._append_bridge_log(
            f"DeckSoundpad Decky bridge loaded version={__version__} "
            f"public_log_dir={self.paths.public_log_dir}"
        )
        self._start_hotkey_monitor()
        self._start_hidraw_monitor()
        self._start_external_overlay_action_server()
        self._request_backend_start_background()

    async def _unload(self) -> None:
        self._unloading = True
        with self._bridge_lifecycle_lock:
            self._stop_input_monitor_restart_coordinator()
            self._stop_hotkey_monitor()
            self._stop_hidraw_monitor()
            self._stop_external_overlay_action_server()
            self._stop_external_overlay()
            self._stop_healthcheck()
        app = getattr(self, "app", None)
        if app is not None:
            close_backend = getattr(app, "close", None)
            if callable(close_backend):
                await asyncio.to_thread(close_backend)
            else:
                close_player = getattr(app.player, "close", app.player.stop_all)
                await asyncio.to_thread(close_player)
        self.logger.info("DeckSoundpad Decky bridge unloaded")
        self._append_bridge_log("DeckSoundpad Decky bridge unloaded")

    async def get_status(self) -> dict[str, Any]:
        return await self._call_backend(
            "status",
            lambda app: app.quick_status(),
            fallback=self._fallback_status("backend unavailable"),
        )

    async def start_backend(self) -> dict[str, Any]:
        self._request_backend_start_background()
        return await self.get_status()

    async def refresh_library(self) -> dict[str, Any]:
        return await self._call_backend(
            "sounds_refresh",
            lambda app: app.refresh_library(),
            fallback={"ok": False, "error": "backend unavailable", "sounds": []},
        )

    async def repair_audio(self) -> dict[str, Any]:
        await self._call_backend(
            "audio_repair",
            lambda app: app.repair_audio(
                before_restart=self._prepare_bridge_runtime_restart,
                after_restart=self._finish_bridge_runtime_restart,
            ),
            fallback={},
        )
        return await self.get_status()

    async def get_settings(self) -> dict[str, Any]:
        return await self._call_backend(
            "settings",
            lambda app: app.settings_payload(),
            fallback=self.settings.to_dict(),
        )

    async def get_input_devices(self) -> dict[str, Any]:
        try:
            devices = await asyncio.to_thread(discover_overlay_input_devices)
        except Exception as exc:
            self._record_bridge_exception("input device discovery", exc)
            devices = []
        return {
            "devices": [
                {
                    "id": "auto",
                    "name": "Automatic",
                    "path": "",
                    "label": "Automatic (all compatible controllers)",
                },
                *[device for device in devices if device.get("id")],
            ]
        }

    async def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        previous_input_device = self._overlay_input_device()
        result = await self._call_backend(
            "settings_update",
            lambda app: app.update_settings(patch),
            fallback=self.settings.to_dict(),
            payload=patch,
        )
        try:
            self.settings = self._backend().settings
        except Exception:
            self.settings = load_config(self.paths)
        if self._overlay_input_device() != previous_input_device:
            self._request_input_monitor_restart()
        return result

    def _create_backend(self) -> DeckSoundpadApp:
        return DeckSoundpadApp(self.paths, settings=self.settings, logger=self.logger)

    def _prepare_bridge_runtime_restart(self) -> None:
        with self._bridge_lifecycle_lock:
            self._bridge_errors.clear()
            self._append_bridge_log("full runtime restart: bridge teardown started")
            self._stop_input_monitor_restart_coordinator()
            with self._input_monitor_lock:
                self._stop_external_overlay()
                self._stop_hotkey_monitor()
                self._stop_hidraw_monitor()
            action_server_stopped = self._stop_external_overlay_action_server()
            self._stop_healthcheck()
            with self._external_overlay_lock:
                self._external_overlay_visible = False
                self._external_overlay_sounds = []
                self._external_overlay_page = 0
                self._external_overlay_selected_index = 0
                self._external_overlay_message = "Restarting DeckSoundpad"
                self._external_overlay_last_direct_toggle = 0.0
            self._hidraw_action_last_at.clear()
            self._hidraw_stick_direction.clear()
            self._hidraw_stick_last_at.clear()
            self._append_bridge_log("full runtime restart: bridge teardown finished")
            if not action_server_stopped:
                raise RuntimeError("external overlay action server did not stop")

    def _finish_bridge_runtime_restart(self) -> None:
        with self._bridge_lifecycle_lock:
            if self._unloading:
                self._append_bridge_log(
                    "full runtime restart: bridge reinitialization skipped during unload"
                )
                return
            self.settings = self._backend().settings
            with self._input_restart_request_lock:
                self._input_restarts_disabled = False
                self._input_restart_requested.clear()
                thread = self._input_restart_thread
                if thread is None or not thread.is_alive():
                    self._input_restart_thread = None
            self._start_healthcheck()
            self._start_external_overlay_action_server()
            with self._input_monitor_lock:
                self._start_hotkey_monitor()
                self._start_hidraw_monitor()
            self._append_bridge_log("full runtime restart: bridge reinitialization finished")

    def _backend(self) -> DeckSoundpadApp:
        app = getattr(self, "app", None)
        if app is not None:
            return app
        with self._backend_lock:
            app = getattr(self, "app", None)
            if app is None:
                self.app = self._create_backend()
                app = self.app
            return app

    def _overlay_hotkey_button(self) -> str:
        settings = getattr(self._backend(), "settings", self.settings)
        return normalize_overlay_hotkey_button(
            getattr(settings, "overlay_hotkey_button", "l5")
        )

    def _overlay_input_device(self) -> str:
        settings = getattr(self._backend(), "settings", self.settings)
        value = str(getattr(settings, "overlay_input_device", "auto")).lower()
        return value if value == "auto" or value.startswith("evdev:") else "auto"

    async def _call_backend(
        self,
        action: str,
        operation: Callable[[DeckSoundpadApp], dict[str, Any]],
        *,
        fallback: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def call() -> dict[str, Any]:
            response = operation(self._backend())
            self._log_bridge_action(action, "backend response", payload, response)
            return response

        try:
            return await asyncio.to_thread(call)
        except Exception as exc:
            self._record_bridge_exception(action, exc)
            self._log_bridge_action(
                action,
                f"exception fallback returned: {exc}",
                payload,
                fallback,
            )
            return fallback

    def _request_backend_start_background(self) -> None:
        if not hasattr(self, "_backend_lock"):
            self._backend_lock = threading.RLock()
        with self._backend_lock:
            if getattr(self, "_backend_start_completed", False):
                return
            thread = getattr(self, "_backend_start_thread", None)
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._backend_start_worker,
                name="decksoundpad-backend-start",
                daemon=True,
            )
            self._backend_start_thread = thread
            thread.start()

    def _backend_start_worker(self) -> None:
        try:
            app = self._backend()
            self._append_bridge_log("backend initialization: full runtime restart")
            repair_response = app.repair_audio(
                before_restart=self._prepare_bridge_runtime_restart,
                after_restart=self._finish_bridge_runtime_restart,
            )
            self._log_bridge_action("audio_repair", "startup response", None, repair_response)
            self._append_bridge_log("backend initialization: refresh sound library")
            library_response = app.refresh_library()
            self._log_bridge_action("sounds_refresh", "startup response", None, library_response)
            self._backend_start_completed = True
        except Exception as exc:
            self._record_bridge_exception("backend_start_worker", exc)

    def _start_healthcheck(self) -> None:
        if not self.settings.background_healthcheck_enabled:
            self.logger.info("background healthcheck disabled")
            return
        current = getattr(self, "_healthcheck_stop", None)
        if current is not None and not current.is_set():
            return
        self._healthcheck_stop = start_healthcheck_loop(self._backend())

    def _stop_healthcheck(self) -> None:
        stop = getattr(self, "_healthcheck_stop", None)
        if stop is None:
            return
        stop.set()
        thread = getattr(stop, "_decksoundpad_thread", None)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._healthcheck_stop = None

    def _start_hotkey_monitor(self) -> None:
        if not _input_hotkey_monitor_enabled():
            self._append_bridge_log("Overlay OS hotkey monitor disabled: no root input access")
            return
        if self._hotkey_thread is not None and self._hotkey_thread.is_alive():
            return
        self._hotkey_stop.clear()
        self._hotkey_thread = threading.Thread(
            target=self._hotkey_monitor_worker,
            name="decksoundpad-overlay-hotkey",
            daemon=True,
        )
        self._hotkey_thread.start()

    def _stop_hotkey_monitor(self) -> None:
        stop = getattr(self, "_hotkey_stop", None)
        if stop is not None:
            stop.set()
        thread = getattr(self, "_hotkey_thread", None)
        if thread is not None and thread.is_alive():
            thread.join()
        if thread is None or not thread.is_alive():
            self._hotkey_thread = None

    def _start_hidraw_monitor(self) -> None:
        if not _input_hotkey_monitor_enabled():
            self._append_bridge_log("Steam Deck HID monitor disabled: no root hidraw access")
            return
        if self._hidraw_thread is not None and self._hidraw_thread.is_alive():
            return
        self._hidraw_stop.clear()
        self._hidraw_thread = threading.Thread(
            target=self._hidraw_monitor_worker,
            name="decksoundpad-steamdeck-hidraw",
            daemon=True,
        )
        self._hidraw_thread.start()

    def _stop_hidraw_monitor(self) -> None:
        stop = getattr(self, "_hidraw_stop", None)
        if stop is not None:
            stop.set()
        thread = getattr(self, "_hidraw_thread", None)
        if thread is not None and thread.is_alive():
            thread.join()
        if thread is None or not thread.is_alive():
            self._hidraw_thread = None

    def _request_input_monitor_restart(self) -> None:
        with self._input_restart_request_lock:
            if self._input_restarts_disabled:
                return
            self._input_restart_requested.set()
            thread = self._input_restart_thread
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._input_monitor_restart_coordinator,
                name="decksoundpad-input-restart",
                daemon=True,
            )
            self._input_restart_thread = thread
            thread.start()

    def _input_monitor_restart_coordinator(self) -> None:
        while True:
            self._input_restart_requested.clear()
            self._restart_input_monitors()
            with self._input_restart_request_lock:
                if self._input_restart_requested.is_set() and not self._input_restarts_disabled:
                    continue
                self._input_restart_thread = None
                return

    def _stop_input_monitor_restart_coordinator(self) -> None:
        with self._input_restart_request_lock:
            self._input_restarts_disabled = True
            self._input_restart_requested.clear()
            thread = self._input_restart_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join()

    def _restart_input_monitors(self) -> None:
        with self._input_monitor_lock:
            self._release_external_overlay_input_grab()
            self._stop_hotkey_monitor()
            self._stop_hidraw_monitor()
            with self._input_restart_request_lock:
                should_start = not self._input_restarts_disabled
            if not should_start:
                return
            self._start_hotkey_monitor()
            self._start_hidraw_monitor()
            self._sync_external_overlay_input_grab()

    def _external_overlay_socket_path(self) -> Path:
        return self._external_overlay_runtime_dir() / EXTERNAL_OVERLAY_SOCKET_NAME

    def _external_overlay_action_socket_path(self) -> Path:
        return self._external_overlay_runtime_dir() / EXTERNAL_OVERLAY_ACTION_SOCKET_NAME

    def _external_overlay_log_file(self) -> Path:
        return self.paths.public_log_dir / EXTERNAL_OVERLAY_LOG_NAME

    def _external_overlay_script(self) -> Path:
        return BACKEND_DIR / "decksoundpad" / "external_overlay.py"

    def _external_overlay_target_identity(self) -> tuple[int, int, str, Path] | None:
        try:
            stat_result = self.paths.user_home.stat()
            passwd = pwd.getpwuid(stat_result.st_uid)
        except (KeyError, OSError):
            return None
        return stat_result.st_uid, stat_result.st_gid, passwd.pw_name, self.paths.user_home

    def _external_overlay_owner(self) -> tuple[int, int] | None:
        """Return the Steam user's ownership pair when the bridge can apply it."""

        identity = self._external_overlay_target_identity()
        if identity is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
            return None
        return identity[0], identity[1]

    def _external_overlay_runtime_dir(self) -> Path:
        identity = self._external_overlay_target_identity()
        if identity is None:
            return self.paths.runtime_dir / "external-overlay"
        uid, _gid, _username, _home = identity
        user_runtime = Path(f"/run/user/{uid}")
        # The GTK overlay must share the Steam user's runtime directory so it can
        # reach the same X11/Gamescope sockets as the active session.
        if user_runtime.exists():
            return user_runtime / "decksoundpad"
        return self.paths.runtime_dir / "external-overlay"

    def _external_overlay_env(self) -> dict[str, str]:
        env = decky_runtime_env(os.environ)
        identity = self._external_overlay_target_identity()
        if identity is not None:
            uid, _gid, username, home = identity
            env["HOME"] = str(home)
            env["USER"] = username
            env["LOGNAME"] = username
            user_runtime = Path(f"/run/user/{uid}")
            if user_runtime.exists():
                env["XDG_RUNTIME_DIR"] = str(user_runtime)

            xauthority_candidates = [
                Path(env["XDG_RUNTIME_DIR"]) / "gamescope" / "Xauthority",
                home / ".Xauthority",
            ]
            for candidate in xauthority_candidates:
                if candidate.exists():
                    env["XAUTHORITY"] = str(candidate)
                    break

        env["GDK_BACKEND"] = "x11"
        env.setdefault("DISPLAY", ":0")
        # Gamescope exposes an X11 path for external overlays; forcing X11 avoids
        # GTK choosing Wayland and missing the overlay-specific X atoms.
        env.pop("WAYLAND_DISPLAY", None)
        return env

    def _prepare_external_overlay_runtime_dir(self, path: Path) -> None:
        ensure_directory(path, mode=0o700, owner=self._external_overlay_owner())

    def _prepare_external_overlay_log_file(self, path: Path) -> None:
        owner = self._external_overlay_owner()
        ensure_directory(path.parent, mode=0o750, owner=owner)
        with open_regular_file(
            path,
            "a",
            encoding="utf-8",
            permissions=0o640,
            enforce_permissions=True,
            owner=owner,
        ):
            pass

    def _start_external_overlay_action_server(self) -> None:
        thread = getattr(self, "_external_overlay_action_thread", None)
        if thread is not None and thread.is_alive():
            stop = getattr(self, "_external_overlay_action_stop", None)
            if stop is not None and stop.is_set():
                thread.join(timeout=2.0)
            if thread.is_alive():
                raise RuntimeError("previous external overlay action server is still stopping")
        stop = threading.Event()
        self._external_overlay_action_stop = stop
        thread = threading.Thread(
            target=self._external_overlay_action_server_worker,
            args=(stop,),
            name="decksoundpad-overlay-actions",
            daemon=True,
        )
        self._external_overlay_action_thread = thread
        thread.start()

    def _stop_external_overlay_action_server(self) -> bool:
        stop = getattr(self, "_external_overlay_action_stop", None)
        if stop is not None:
            stop.set()
        server = getattr(self, "_external_overlay_action_server_socket", None)
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.settimeout(0.05)
                client.connect(str(self._external_overlay_action_socket_path()))
            finally:
                client.close()
        except OSError:
            pass
        thread = getattr(self, "_external_overlay_action_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        if thread is not None and thread.is_alive():
            self._append_bridge_log("external overlay action server did not stop")
            return False
        self._external_overlay_action_thread = None
        return True

    def _external_overlay_action_server_worker(self, stop: threading.Event) -> None:
        socket_path = self._external_overlay_action_socket_path()
        try:
            self._prepare_external_overlay_runtime_dir(socket_path.parent)
            socket_path.unlink(missing_ok=True)
        except OSError as exc:
            self._append_bridge_log(f"external overlay action socket prepare failed: {exc}")
            return

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._external_overlay_action_server_socket = server
        try:
            server.bind(str(socket_path))
            self._prepare_external_overlay_socket_file(socket_path, mode=0o600)
            server.listen(8)
            server.settimeout(0.5)
            self._append_bridge_log(f"external overlay action socket listening path={socket_path}")
            while not stop.is_set():
                try:
                    client, _addr = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(0.5)
                    try:
                        payload = client.recv(64 * 1024)
                    except socket.timeout:
                        continue
                    if not payload:
                        continue
                    for line in payload.splitlines():
                        try:
                            command = json.loads(line.decode("utf-8"))
                        except json.JSONDecodeError as exc:
                            self._append_bridge_log(f"external overlay action invalid json: {exc}")
                            continue
                        # Touch events originate in the overlay process; handle
                        # them here so playback and selection state stay in one place.
                        self._handle_external_overlay_action(command)
        except OSError as exc:
            if not stop.is_set():
                self._append_bridge_log(f"external overlay action socket failed: {exc}")
        finally:
            server.close()
            if self._external_overlay_action_server_socket is server:
                self._external_overlay_action_server_socket = None
            try:
                socket_path.unlink()
            except FileNotFoundError:
                pass

    def _prepare_external_overlay_socket_file(self, path: Path, *, mode: int) -> None:
        try:
            set_socket_metadata(path, owner=self._external_overlay_owner(), mode=mode)
        except OSError as exc:
            self._append_bridge_log(f"external overlay socket metadata failed: {exc}")

    def _handle_external_overlay_action(self, command: dict[str, Any]) -> None:
        if not isinstance(command, dict):
            return
        command_type = command.get("type")
        if command_type == "input":
            action = clean_log_text(str(command.get("action", "")), 40)
            if action:
                self._append_bridge_log(f"external overlay touch action input={action}")
                self._handle_external_overlay_input(action)
            return

        if command_type != "select":
            return

        try:
            requested_index = int(command.get("index", 0))
        except (TypeError, ValueError):
            requested_index = 0
        play = bool(command.get("play"))

        with self._external_overlay_lock:
            if not self._external_overlay_visible:
                return
            visible_sounds = self._external_overlay_visible_sounds()
            if not visible_sounds:
                return
            self._external_overlay_selected_index = clamp_number(
                requested_index,
                0,
                len(visible_sounds) - 1,
            )
            self._append_bridge_log(
                "external overlay touch select "
                f"index={self._external_overlay_selected_index} play={play}"
            )
            if play:
                self._play_external_overlay_selection()
            self._send_external_overlay_state()

    def _check_external_overlay_runtime(self, python: str, env: dict[str, str]) -> None:
        check_script = (
            "import cairo\n"
            "import gi\n"
            "gi.require_version('Gtk', '3.0')\n"
            "gi.require_version('Gdk', '3.0')\n"
            "from gi.repository import Gdk, Gtk\n"
            "ok, _argv = Gtk.init_check([])\n"
            "raise SystemExit(0 if ok else 2)\n"
        )
        try:
            result = subprocess.run(
                [python, "-c", check_script],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.5,
                env=env,
                **subprocess_user_kwargs(self.paths.user_home),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"external overlay python not found: {python}") from exc
        except subprocess.TimeoutExpired as exc:
            output = clean_log_text(" ".join(str(part or "") for part in (exc.stdout, exc.stderr)), 240)
            raise RuntimeError(f"external overlay runtime check timed out: {output}") from exc

        if result.returncode == 0:
            return

        output = clean_log_text("\n".join(part for part in (result.stdout, result.stderr) if part), 320)
        if not output:
            output = (
                f"Gtk.init_check failed display={env.get('DISPLAY', '<unset>')} "
                f"xauthority={env.get('XAUTHORITY', '<unset>')} user={env.get('USER', '<unset>')}"
            )
        raise RuntimeError(f"external overlay runtime check failed: {output}")

    def _external_overlay_log_tail(self, lines: int = 12) -> str:
        try:
            content = self._external_overlay_log_file().read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            return ""
        return clean_log_text(" | ".join(content[-lines:]), 500)

    def _external_overlay_process_exit_error(self) -> str | None:
        process = self._external_overlay_process
        if process is None:
            return None
        returncode = process.poll()
        if returncode is None:
            return None
        tail = self._external_overlay_log_tail()
        if tail:
            return f"external overlay exited rc={returncode}: {tail}"
        return f"external overlay exited rc={returncode}"

    def _ensure_external_overlay_process(self) -> None:
        with self._external_overlay_lock:
            process = self._external_overlay_process
            if process is not None and process.poll() is None:
                return
            if process is not None:
                tail = self._external_overlay_log_tail()
                detail = f"external overlay previous process exited rc={process.poll()}"
                if tail:
                    detail = f"{detail}: {tail}"
                self._append_bridge_log(detail)

            socket_path = self._external_overlay_socket_path()
            action_socket_path = self._external_overlay_action_socket_path()
            try:
                socket_path.unlink()
            except FileNotFoundError:
                pass

            self._prepare_external_overlay_runtime_dir(socket_path.parent)
            env = self._external_overlay_env()
            python = env.get("DECKSOUNDPAD_OVERLAY_PYTHON") or "/usr/bin/python3"
            self._check_external_overlay_runtime(python, env)
            log_file = self._external_overlay_log_file()
            self._prepare_external_overlay_log_file(log_file)
            args = [
                python,
                str(self._external_overlay_script()),
                "--socket",
                str(socket_path),
                "--actions-socket",
                str(action_socket_path),
                "--log",
                str(log_file),
            ]
            owner = self._external_overlay_owner()
            with open_regular_file(
                log_file,
                "a",
                encoding="utf-8",
                permissions=0o640,
                enforce_permissions=True,
                owner=owner,
            ) as log_handle:
                self._external_overlay_process = subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=log_handle,
                    env=env,
                    start_new_session=True,
                    **subprocess_user_kwargs(self.paths.user_home),
                )
            uid_fragment = ""
            identity = self._external_overlay_target_identity()
            if identity is not None:
                uid, _gid, username, _home = identity
                uid_fragment = f" user={username} uid={uid}"
            self._append_bridge_log(
                "external overlay spawned "
                f"pid={self._external_overlay_process.pid} socket={socket_path}{uid_fragment}"
            )

    def _stop_external_overlay(self) -> None:
        with self._external_overlay_lock:
            self._external_overlay_visible = False
            process = getattr(self, "_external_overlay_process", None)
        self._release_external_overlay_input_grab()
        if process is None:
            return
        try:
            self._send_external_overlay_command({"type": "quit"}, start_process=False)
        except Exception:
            pass
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=0.75)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self._append_bridge_log(
                    f"external overlay did not exit after kill pid={process.pid}"
                )
        finally:
            with self._external_overlay_lock:
                if self._external_overlay_process is process:
                    self._external_overlay_process = None

    def _grab_external_overlay_input_devices(self) -> None:
        if self._external_overlay_input_grab_handles or self._external_overlay_input_grab_attempted:
            return
        self._external_overlay_input_grab_attempted = True
        if fcntl is None:
            self._append_bridge_log("external overlay input grab unavailable: missing fcntl")
            return

        selector = self._overlay_input_device()
        devices = filter_overlay_input_devices(discover_overlay_input_devices(), selector)
        grabbed: list[tuple[str, str, Any]] = []
        for device in devices:
            path_text = device["path"]
            name = device["name"]
            try:
                handle = Path(path_text).open("rb", buffering=0)
                os.set_blocking(handle.fileno(), False)
            except OSError:
                continue
            try:
                fcntl.ioctl(handle.fileno(), EVIOCGRAB, 1)
            except OSError as exc:
                self._append_bridge_log(
                    f"external overlay input grab failed device={path_text} name={name!r}: {exc}"
                )
                try:
                    handle.close()
                except OSError:
                    pass
                continue
            grabbed.append((path_text, name, handle))

        self._external_overlay_input_grab_handles = grabbed
        if grabbed:
            devices = ",".join(f"{path}:{name or 'unknown'}" for path, name, _handle in grabbed)
            self._append_bridge_log(f"external overlay input grab enabled devices={devices}")
            self._start_external_overlay_evdev_reader()
        else:
            self._append_bridge_log("external overlay input grab found no gamepad event devices")

    def _start_external_overlay_evdev_reader(self) -> None:
        thread = getattr(self, "_external_overlay_evdev_thread", None)
        if thread is not None and thread.is_alive():
            return
        stop = threading.Event()
        self._external_overlay_evdev_stop = stop
        thread = threading.Thread(
            target=self._external_overlay_evdev_worker,
            args=(stop,),
            name="decksoundpad-overlay-evdev",
            daemon=True,
        )
        self._external_overlay_evdev_thread = thread
        thread.start()

    def _external_overlay_evdev_worker(self, stop: threading.Event) -> None:
        self._append_bridge_log("external overlay selected evdev reader started")
        while not stop.is_set() and self._external_overlay_visible:
            handles = list(self._external_overlay_input_grab_handles)
            if not handles:
                break
            try:
                readable, _writable, _errored = select.select(
                    [handle for _path, _name, handle in handles],
                    [],
                    [],
                    0.5,
                )
            except (OSError, ValueError):
                break
            for handle in readable:
                device_path = next(
                    (path for path, _name, candidate in handles if candidate is handle),
                    "<unknown>",
                )
                while not stop.is_set():
                    try:
                        data = os.read(handle.fileno(), INPUT_EVENT_SIZE)
                    except BlockingIOError:
                        break
                    except OSError:
                        stop.set()
                        break
                    if len(data) != INPUT_EVENT_SIZE:
                        break
                    _sec, _usec, event_type, code, value = INPUT_EVENT_STRUCT.unpack(data)
                    if event_type == EV_KEY and value == 1:
                        self._handle_external_overlay_evdev_press(
                            code,
                            device_path,
                            stop,
                        )
        self._append_bridge_log("external overlay selected evdev reader stopped")

    def _handle_external_overlay_evdev_press(
        self,
        code: int,
        device_path: str,
        reader_stop: threading.Event | None = None,
    ) -> None:
        with self._external_overlay_lock:
            if reader_stop is not None and reader_stop.is_set():
                return
            hotkey_button = self._overlay_hotkey_button()
            if code in overlay_hotkey_event_codes(
                hotkey_button,
                include_legacy_l5=self._overlay_input_device() == "auto",
            ):
                self._handle_overlay_direct_hotkey("evdev-grab")
                return
            action = EVDEV_OVERLAY_ACTIONS.get(code)
            if action is not None:
                self._handle_debounced_overlay_action(
                    action,
                    "evdev-grab",
                    device_path,
                )
                return
            if hotkey_button != "r5" and code in overlay_hotkey_event_codes("r5"):
                self._handle_r5_direct_previous_sound("evdev-grab", device_path)

    def _release_external_overlay_input_grab(self) -> None:
        with self._external_overlay_lock:
            stop = getattr(self, "_external_overlay_evdev_stop", None)
            if stop is not None:
                stop.set()
            thread = getattr(self, "_external_overlay_evdev_thread", None)
            handles = list(getattr(self, "_external_overlay_input_grab_handles", []))
            self._external_overlay_input_grab_handles = []
            self._external_overlay_input_grab_attempted = False
        for path, name, handle in handles:
            try:
                if fcntl is not None:
                    fcntl.ioctl(handle.fileno(), EVIOCGRAB, 0)
            except OSError as exc:
                self._append_bridge_log(
                    f"external overlay input grab release failed device={path} name={name!r}: {exc}"
                )
            try:
                handle.close()
            except OSError:
                pass
        if handles:
            self._append_bridge_log("external overlay input grab released")
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._external_overlay_lock:
            if thread is None or not thread.is_alive():
                self._external_overlay_evdev_thread = None

    def _sync_external_overlay_input_grab(self) -> None:
        with self._external_overlay_lock:
            if self._external_overlay_visible:
                self._grab_external_overlay_input_devices()
            else:
                self._release_external_overlay_input_grab()

    def _send_external_overlay_command(
        self,
        command: dict[str, Any],
        *,
        start_process: bool = True,
    ) -> None:
        if start_process:
            self._ensure_external_overlay_process()

        encoded = (json.dumps(command, ensure_ascii=True) + "\n").encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(16):
            if start_process:
                exit_error = self._external_overlay_process_exit_error()
                if exit_error is not None:
                    raise RuntimeError(exit_error)
            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    client.settimeout(0.35)
                    client.connect(str(self._external_overlay_socket_path()))
                    client.sendall(encoded)
                    return
                finally:
                    client.close()
            except OSError as exc:
                last_error = exc
                if attempt == 3 and start_process:
                    self._ensure_external_overlay_process()
                # The overlay process creates its socket after GTK starts, so a
                # short retry window keeps toggle input from racing startup.
                time.sleep(0.08)
        tail = self._external_overlay_log_tail()
        detail = f"external overlay socket unavailable: {last_error}"
        if tail:
            detail = f"{detail}; log: {tail}"
        raise RuntimeError(detail)

    def _toggle_external_overlay(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._external_overlay_lock:
            source = clean_log_text(str(payload.get("source", "unknown")))
            now = time.monotonic()
            is_direct_input = source in STEAM_DECK_HID_DIRECT_SOURCES
            elapsed_since_direct = now - self._external_overlay_last_direct_toggle
            if is_direct_input and elapsed_since_direct < DIRECT_INPUT_TOGGLE_DEDUP_SECONDS:
                self._append_bridge_log(
                    "external overlay duplicate direct toggle ignored "
                    f"visible={self._external_overlay_visible} source={source}"
                )
                return {
                    "ok": True,
                    "visible": self._external_overlay_visible,
                    "sounds_count": len(self._external_overlay_sounds),
                    "deduped": True,
                }
            if not is_direct_input and elapsed_since_direct < FRONTEND_AFTER_DIRECT_DEDUP_SECONDS:
                # The same rear-button press can arrive through hidraw and then
                # through the Decky UI bridge; keep the first toggle and ignore the echo.
                self._append_bridge_log(
                    "external overlay duplicate frontend toggle ignored "
                    f"visible={self._external_overlay_visible} source={source}"
                )
                return {
                    "ok": True,
                    "visible": self._external_overlay_visible,
                    "sounds_count": len(self._external_overlay_sounds),
                    "deduped": True,
                }

            previous_visible = self._external_overlay_visible
            self._external_overlay_visible = not self._external_overlay_visible
            self._external_overlay_message = "Ready"
            try:
                self._reload_external_overlay_sounds()
                self._send_external_overlay_state()
            except Exception:
                self._external_overlay_visible = previous_visible
                self._sync_external_overlay_input_grab()
                raise
            if is_direct_input:
                self._external_overlay_last_direct_toggle = now
            self._append_bridge_log(
                "external overlay toggle "
                f"visible={self._external_overlay_visible} source={source}"
            )
            return {
                "ok": True,
                "visible": self._external_overlay_visible,
                "sounds_count": len(self._external_overlay_sounds),
            }

    def _handle_external_overlay_input(self, action: str) -> dict[str, Any]:
        safe_action = clean_log_text(str(action), 40)
        with self._external_overlay_lock:
            if not self._external_overlay_visible:
                return {"ok": True, "visible": False}

            if action == "hide":
                self._external_overlay_visible = False
            elif action in {"next", "right"}:
                self._move_external_overlay_selection(1)
            elif action in {"prev", "left"}:
                self._move_external_overlay_selection(-1)
            elif action == "down":
                self._move_external_overlay_selection_vertical(1)
            elif action == "up":
                self._move_external_overlay_selection_vertical(-1)
            elif action == "page_next":
                self._move_external_overlay_page(1)
            elif action == "page_prev":
                self._move_external_overlay_page(-1)
            elif action == "play":
                self._play_external_overlay_selection()
            else:
                return {"ok": False, "visible": self._external_overlay_visible, "error": f"unknown action: {safe_action}"}

            self._send_external_overlay_state()
            return {
                "ok": True,
                "visible": self._external_overlay_visible,
                "action": safe_action,
                "page": self._external_overlay_page,
                "selected_index": self._external_overlay_selected_index,
            }

    def _reload_external_overlay_sounds(self) -> None:
        response = self._backend().list_sounds()
        sounds = response.get("sounds") if isinstance(response, dict) else []
        self._external_overlay_sounds = [sound for sound in sounds if isinstance(sound, dict)]
        page_count = self._external_overlay_page_count()
        self._external_overlay_page = clamp_number(self._external_overlay_page, 0, page_count - 1)
        self._external_overlay_selected_index = clamp_number(
            self._external_overlay_selected_index,
            0,
            max(0, len(self._external_overlay_visible_sounds()) - 1),
        )

    def _external_overlay_page_count(self) -> int:
        return max(1, (len(self._external_overlay_sounds) + EXTERNAL_OVERLAY_SOUNDS_PER_PAGE - 1) // EXTERNAL_OVERLAY_SOUNDS_PER_PAGE)

    def _external_overlay_visible_sounds(self) -> list[dict[str, Any]]:
        start = self._external_overlay_page * EXTERNAL_OVERLAY_SOUNDS_PER_PAGE
        return self._external_overlay_sounds[start : start + EXTERNAL_OVERLAY_SOUNDS_PER_PAGE]

    def _external_overlay_absolute_index(self) -> int:
        if not self._external_overlay_sounds:
            return 0
        absolute_index = (
            self._external_overlay_page * EXTERNAL_OVERLAY_SOUNDS_PER_PAGE
            + self._external_overlay_selected_index
        )
        return clamp_number(absolute_index, 0, len(self._external_overlay_sounds) - 1)

    def _set_external_overlay_absolute_index(self, absolute_index: int) -> None:
        if not self._external_overlay_sounds:
            self._external_overlay_page = 0
            self._external_overlay_selected_index = 0
            return
        safe_index = absolute_index % len(self._external_overlay_sounds)
        self._external_overlay_page = safe_index // EXTERNAL_OVERLAY_SOUNDS_PER_PAGE
        self._external_overlay_selected_index = safe_index % EXTERNAL_OVERLAY_SOUNDS_PER_PAGE

    def _move_external_overlay_absolute_selection(self, direction: int) -> None:
        if not self._external_overlay_sounds:
            self._external_overlay_page = 0
            self._external_overlay_selected_index = 0
            return
        self._set_external_overlay_absolute_index(
            self._external_overlay_absolute_index() + direction
        )

    def _move_external_overlay_selection(self, direction: int) -> None:
        visible_sounds = self._external_overlay_visible_sounds()
        if not visible_sounds:
            self._external_overlay_selected_index = 0
            return
        self._external_overlay_selected_index = (
            self._external_overlay_selected_index + direction
        ) % len(visible_sounds)

    def _move_external_overlay_selection_vertical(self, direction: int) -> None:
        visible_sounds = self._external_overlay_visible_sounds()
        if not visible_sounds:
            self._external_overlay_selected_index = 0
            return
        row_count = max(1, (len(visible_sounds) + EXTERNAL_OVERLAY_GRID_COLUMNS - 1) // EXTERNAL_OVERLAY_GRID_COLUMNS)
        current_index = clamp_number(
            self._external_overlay_selected_index,
            0,
            len(visible_sounds) - 1,
        )
        current_row = current_index // EXTERNAL_OVERLAY_GRID_COLUMNS
        current_column = current_index % EXTERNAL_OVERLAY_GRID_COLUMNS
        next_row = (current_row + direction) % row_count
        next_index = min(next_row * EXTERNAL_OVERLAY_GRID_COLUMNS + current_column, len(visible_sounds) - 1)
        self._external_overlay_selected_index = next_index

    def _move_external_overlay_page(self, direction: int) -> None:
        page_count = self._external_overlay_page_count()
        self._external_overlay_page = (self._external_overlay_page + direction) % page_count
        self._external_overlay_selected_index = 0

    def _play_external_overlay_selection(self) -> None:
        visible_sounds = self._external_overlay_visible_sounds()
        sound = visible_sounds[self._external_overlay_selected_index] if visible_sounds else None
        sound_id = sound.get("id") if isinstance(sound, dict) else None
        if not isinstance(sound_id, str):
            self._external_overlay_message = "No sound selected"
            return
        response = self._backend().play_sound({"sound_id": sound_id, "volume": None})
        if response.get("ok"):
            self._external_overlay_message = f"Played {sound.get('display_name') or sound.get('relative_path') or 'sound'}"
            self._external_overlay_visible = False
        else:
            self._external_overlay_message = clean_log_text(str(response.get("error") or "Playback failed"), 80)

    def _play_previous_external_overlay_sound(self) -> dict[str, Any]:
        with self._external_overlay_lock:
            was_visible = self._external_overlay_visible
            self._reload_external_overlay_sounds()
            if not self._external_overlay_sounds:
                self._external_overlay_message = "No sounds found"
                if was_visible:
                    self._send_external_overlay_state()
                return {
                    "ok": False,
                    "visible": self._external_overlay_visible,
                    "error": "no sounds found",
                    "page": self._external_overlay_page,
                    "selected_index": self._external_overlay_selected_index,
                }

            self._move_external_overlay_absolute_selection(-1)
            self._play_external_overlay_selection()
            if was_visible:
                self._send_external_overlay_state()
            return {
                "ok": True,
                "visible": self._external_overlay_visible,
                "page": self._external_overlay_page,
                "selected_index": self._external_overlay_selected_index,
                "sounds_count": len(self._external_overlay_sounds),
            }

    def _send_external_overlay_state(self) -> None:
        visible_sounds = self._external_overlay_visible_sounds()
        command = {
            "type": "state",
            "visible": self._external_overlay_visible,
            "sounds": [
                {
                    "id": sound.get("id"),
                    "display_name": sound.get("display_name"),
                    "relative_path": sound.get("relative_path"),
                }
                for sound in visible_sounds
            ],
            "selected_index": self._external_overlay_selected_index,
            "page": self._external_overlay_page,
            "page_count": self._external_overlay_page_count(),
            "total_count": len(self._external_overlay_sounds),
            "message": self._external_overlay_message,
            "overlay_hotkey_button": self._overlay_hotkey_button().upper(),
        }
        if self._external_overlay_visible:
            # Grab before showing state so the game does not also receive the
            # button press that opens and navigates the overlay.
            self._sync_external_overlay_input_grab()
        self._send_external_overlay_command(command)
        if not self._external_overlay_visible:
            self._sync_external_overlay_input_grab()

    def _hidraw_monitor_worker(self) -> None:
        if self._overlay_input_device() != "auto":
            self._append_bridge_log(
                "Steam Deck HID monitor disabled: explicit evdev input device selected"
            )
            return
        self._append_bridge_log("Steam Deck HID monitor starting")
        previous_buttons: dict[str, int] = {}
        seen_report_devices: set[str] = set()
        while not self._hidraw_stop.is_set():
            handles = self._open_hidraw_devices()
            if not handles:
                self._append_bridge_log("Steam Deck HID monitor found no readable /dev/hidraw* devices")
                self._hidraw_stop.wait(5.0)
                continue
            self._append_bridge_log(
                "Steam Deck HID monitor opened devices="
                + ",".join(path for path, _handle in handles)
            )
            try:
                while not self._hidraw_stop.is_set():
                    readable, _writable, _errored = select.select(
                        [handle for _path, handle in handles],
                        [],
                        [],
                        1.0,
                    )
                    for handle in readable:
                        device_path = next(
                            (path for path, candidate in handles if candidate is handle),
                            "<unknown>",
                        )
                        while True:
                            try:
                                data = os.read(handle.fileno(), 64)
                            except BlockingIOError:
                                break
                            except OSError as exc:
                                self._append_bridge_log(f"Steam Deck HID read failed: {exc}")
                                raise
                            if not data:
                                break
                            report = parse_steam_deck_hid_report(data)
                            if report is None:
                                continue
                            buttons_l = int(report["buttons_l"])
                            buttons_h = int(report["buttons_h"])
                            buttons = buttons_l | (buttons_h << 32)
                            if device_path not in seen_report_devices:
                                seen_report_devices.add(device_path)
                                self._append_bridge_log(
                                    "Steam Deck HID state report detected "
                                    f"device={device_path} offset={report['offset']} "
                                    f"buttons_l=0x{buttons_l:08x} buttons_h=0x{buttons_h:08x}"
                                )
                            previous = previous_buttons.get(device_path)
                            previous_buttons[device_path] = buttons
                            if previous is None:
                                # The first report is a baseline; only edge
                                # transitions after that should trigger actions.
                                continue
                            pressed = buttons & ~previous
                            hotkey_button = self._overlay_hotkey_button()
                            hotkey_mask = overlay_hotkey_button_mask(hotkey_button)
                            if pressed & hotkey_mask:
                                self._append_bridge_log(
                                    "Steam Deck HID overlay hotkey press "
                                    f"button={hotkey_button.upper()} device={device_path} "
                                    f"buttons_l=0x{buttons_l:08x} buttons_h=0x{buttons_h:08x}"
                                )
                                self._handle_overlay_direct_hotkey("hidraw-input")
                                continue
                            if hotkey_button != "r5" and pressed & STEAM_DECK_LBUTTON_R5:
                                self._append_bridge_log(
                                    "Steam Deck HID R5 press "
                                    f"device={device_path} buttons_l=0x{buttons_l:08x} "
                                    f"buttons_h=0x{buttons_h:08x}"
                                )
                                self._handle_r5_direct_previous_sound("hidraw-input", device_path)
                                continue
                            if self._external_overlay_visible:
                                if pressed:
                                    self._handle_hidraw_overlay_buttons(pressed, device_path)
                                if self._external_overlay_visible:
                                    self._handle_hidraw_overlay_sticks(report, device_path)
            except OSError:
                self._hidraw_stop.wait(1.0)
            finally:
                for _path, handle in handles:
                    try:
                        handle.close()
                    except OSError:
                        pass
        self._append_bridge_log("Steam Deck HID monitor stopped")

    def _open_hidraw_devices(self) -> list[tuple[str, Any]]:
        if self._overlay_input_device() != "auto":
            return []
        handles: list[tuple[str, Any]] = []
        try:
            hidraw_paths = sorted(Path("/dev").glob("hidraw*"))
        except OSError as exc:
            self._append_bridge_log(f"Steam Deck HID device scan failed: {exc}")
            return []
        for path in hidraw_paths:
            try:
                handle = path.open("rb", buffering=0)
                os.set_blocking(handle.fileno(), False)
            except OSError as exc:
                self._append_bridge_log(f"Steam Deck HID cannot open {path}: {exc}")
                continue
            handles.append((str(path), handle))
        return handles

    def _handle_debounced_overlay_action(
        self,
        action: str,
        source: str,
        device_path: str,
    ) -> bool:
        with self._external_overlay_lock:
            now = time.monotonic()
            last_at = self._hidraw_action_last_at.get(action, 0.0)
            if now - last_at < HIDRAW_ACTION_DEBOUNCE_SECONDS:
                self._append_bridge_log(
                    "Overlay input action debounced "
                    f"source={source} device={device_path} action={action}"
                )
                return False
            self._hidraw_action_last_at[action] = now
            self._append_bridge_log(
                "Overlay input action "
                f"source={source} device={device_path} action={action}"
            )
            try:
                response = self._handle_external_overlay_input(action)
                self._append_bridge_log(
                    "Overlay input action handled "
                    f"source={source} action={action} "
                    f"visible={bool(response.get('visible'))}"
                )
            except Exception as exc:
                self._record_bridge_exception(
                    f"handle overlay action {action} from {source}",
                    exc,
                )
                return False
            return True

    def _handle_hidraw_overlay_buttons(self, pressed: int, device_path: str) -> None:
        for mask, action in STEAM_DECK_HID_ACTIONS:
            if not pressed & mask:
                continue
            self._handle_debounced_overlay_action(
                action,
                "hidraw-input",
                device_path,
            )
            return

    def _handle_hidraw_overlay_sticks(self, report: dict[str, int], device_path: str) -> None:
        direction = dominant_steam_deck_stick_direction(report)
        if direction is None:
            self._hidraw_stick_direction[device_path] = None
            return

        now = time.monotonic()
        previous_direction = self._hidraw_stick_direction.get(device_path)
        previous_at = self._hidraw_stick_last_at.get(device_path, 0.0)
        if direction == previous_direction and now - previous_at < HIDRAW_STICK_NAVIGATION_REPEAT_SECONDS:
            return

        self._hidraw_stick_direction[device_path] = direction
        self._hidraw_stick_last_at[device_path] = now
        self._append_bridge_log(
            "Steam Deck HID overlay stick input "
            f"device={device_path} direction={direction} "
            f"left=({report.get('left_stick_x', 0)},{report.get('left_stick_y', 0)}) "
            f"right=({report.get('right_stick_x', 0)},{report.get('right_stick_y', 0)})"
        )
        try:
            response = self._handle_external_overlay_input(direction)
            self._append_bridge_log(
                "Steam Deck HID overlay stick input handled "
                f"direction={direction} visible={bool(response.get('visible'))}"
            )
        except Exception as exc:
            self._record_bridge_exception(f"handle Steam Deck HID stick direction {direction}", exc)

    def _hotkey_monitor_worker(self) -> None:
        self._append_bridge_log("Overlay OS hotkey monitor starting")
        last_emit = 0.0
        diagnostic_presses = 0
        seen_press_codes: set[tuple[str, int]] = set()
        while not self._hotkey_stop.is_set():
            handles = self._open_input_event_devices()
            if not handles:
                self._append_bridge_log(
                    "Overlay OS hotkey monitor found no readable /dev/input/event* devices"
                )
                self._hotkey_stop.wait(5.0)
                continue
            self._append_bridge_log(
                "Overlay OS hotkey monitor opened devices="
                + ",".join(path for path, _handle in handles)
            )
            try:
                while not self._hotkey_stop.is_set():
                    readable, _writable, _errored = select.select(
                        [handle for _path, handle in handles],
                        [],
                        [],
                        1.0,
                    )
                    for handle in readable:
                        device_path = next(
                            (path for path, candidate in handles if candidate is handle),
                            "<unknown>",
                        )
                        while True:
                            try:
                                data = os.read(handle.fileno(), INPUT_EVENT_SIZE)
                            except BlockingIOError:
                                break
                            except OSError as exc:
                                self._append_bridge_log(f"Overlay OS hotkey read failed: {exc}")
                                raise
                            if len(data) != INPUT_EVENT_SIZE:
                                break
                            _sec, _usec, event_type, code, value = INPUT_EVENT_STRUCT.unpack(data)
                            if event_type != EV_KEY or value != 1:
                                continue
                            if diagnostic_presses < HOTKEY_DIAGNOSTIC_PRESS_LIMIT:
                                key = (device_path, code)
                                if key not in seen_press_codes:
                                    seen_press_codes.add(key)
                                    diagnostic_presses += 1
                                    self._append_bridge_log(
                                        "Overlay OS hotkey observed key press "
                                        f"device={device_path} code={code} "
                                        f"hex=0x{code:x} name={KEY_NAMES.get(code, 'unknown')} "
                                        f"{self._backend_steam_overlay_log_fragment()}"
                                    )
                            hotkey_button = self._overlay_hotkey_button()
                            if code in overlay_hotkey_event_codes(
                                hotkey_button,
                                include_legacy_l5=self._overlay_input_device() == "auto",
                            ):
                                self._append_bridge_log(
                                    "Overlay OS hotkey press "
                                    f"button={hotkey_button.upper()} device={device_path} "
                                    f"code={code} hex=0x{code:x} "
                                    f"name={KEY_NAMES.get(code, 'unknown')} "
                                    f"{self._backend_steam_overlay_log_fragment()}"
                                )
                                now = time.monotonic()
                                if now - last_emit >= HOTKEY_DEBOUNCE_SECONDS:
                                    last_emit = now
                                    self._handle_overlay_direct_hotkey("os-input")
                            elif self._external_overlay_visible and code in EVDEV_OVERLAY_ACTIONS:
                                action = EVDEV_OVERLAY_ACTIONS[code]
                                self._handle_debounced_overlay_action(
                                    action,
                                    "os-input",
                                    device_path,
                                )
                            elif hotkey_button != "r5" and code in overlay_hotkey_event_codes("r5"):
                                self._handle_r5_direct_previous_sound(
                                    "os-input",
                                    device_path,
                                )
            except OSError:
                self._hotkey_stop.wait(1.0)
            finally:
                for _path, handle in handles:
                    try:
                        handle.close()
                    except OSError:
                        pass
        self._append_bridge_log("Overlay OS hotkey monitor stopped")

    def _open_input_event_devices(self) -> list[tuple[str, Any]]:
        handles: list[tuple[str, Any]] = []
        selector = self._overlay_input_device()
        devices = filter_overlay_input_devices(discover_overlay_input_devices(), selector)
        if selector != "auto" and not devices:
            self._append_bridge_log(
                f"Configured overlay input device unavailable: {selector}"
            )
        for device in devices:
            path_text = device["path"]
            try:
                handle = Path(path_text).open("rb", buffering=0)
                os.set_blocking(handle.fileno(), False)
            except OSError as exc:
                self._append_bridge_log(f"Overlay OS hotkey cannot open {path_text}: {exc}")
                continue
            handles.append((path_text, handle))
        return handles

    def _handle_overlay_direct_hotkey(self, source: str) -> None:
        hotkey_button = self._overlay_hotkey_button()
        self._append_bridge_log(
            f"{hotkey_button.upper()} overlay shortcut detected source={source} "
            f"{self._backend_steam_overlay_log_fragment()}"
        )
        try:
            response = self._toggle_external_overlay({"source": source})
            self._append_bridge_log(
                "Overlay direct hotkey handled by backend "
                f"button={hotkey_button.upper()} source={source} "
                f"visible={bool(response.get('visible'))} sounds_count={response.get('sounds_count', 0)}"
            )
        except Exception as exc:
            self._record_bridge_exception(
                f"handle {hotkey_button.upper()} overlay hotkey source={source}",
                exc,
            )

    def _handle_r5_direct_previous_sound(self, source: str, device_path: str) -> None:
        action = "play_previous"
        now = time.monotonic()
        last_at = self._hidraw_action_last_at.get(action, 0.0)
        if now - last_at < HIDRAW_ACTION_DEBOUNCE_SECONDS:
            self._append_bridge_log(
                "R5 direct previous sound debounced "
                f"source={source} device={device_path}"
            )
            return
        self._hidraw_action_last_at[action] = now
        self._append_bridge_log(
            f"R5 direct previous sound detected source={source} device={device_path}"
        )
        try:
            response = self._play_previous_external_overlay_sound()
            self._append_bridge_log(
                "R5 direct previous sound handled "
                f"source={source} visible={bool(response.get('visible'))} "
                f"page={response.get('page')} selected_index={response.get('selected_index')}"
            )
        except Exception as exc:
            self._record_bridge_exception(f"handle R5 direct previous sound source={source}", exc)

    def _fallback_status(self, last_error: str) -> dict[str, Any]:
        settings = getattr(self, "settings", None)
        mic_passthrough_enabled = bool(getattr(settings, "mic_passthrough_enabled", False))
        status = Status(
            backend_running=False,
            audio=AudioStatus(last_error=last_error, state="offline"),
            player=PlayerStatus(
                backend=None,
            ),
            library=LibraryStatus(count=0),
        ).to_dict()
        status["version"] = __version__
        status["mic_passthrough_enabled"] = mic_passthrough_enabled
        status["playback_route"] = {
            "backend": None,
            "virtual_input": "decksoundpad_mic",
            "sink": "decksoundpad_sink",
            "mode": "offline",
        }
        return status

    def _record_bridge_exception(self, context: str, exc: Exception) -> None:
        message = f"bridge {context} failed: {exc}"
        logger = getattr(self, "logger", None)
        if logger is not None:
            try:
                logger.warning(message, exc_info=True)
            except Exception:
                pass
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        self._append_bridge_log(message)
        for line in details.splitlines()[-12:]:
            self._append_bridge_log(line)

    def _append_bridge_log(self, line: str) -> None:
        errors = getattr(self, "_bridge_errors", None)
        if errors is None:
            errors = []
            self._bridge_errors = errors
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry = f"{timestamp} {line}"
        errors.append(entry)
        if len(errors) > 120:
            del errors[:-120]
        self._write_public_bridge_log(entry)

    def _write_public_bridge_log(self, line: str) -> None:
        paths = getattr(self, "paths", None)
        if paths is None:
            return
        try:
            owner = user_owner(paths)
            ensure_directory(paths.public_log_dir, mode=0o750, owner=owner)
            with open_regular_file(
                paths.public_bridge_log_file,
                "a",
                encoding="utf-8",
                permissions=0o640,
                enforce_permissions=True,
                owner=owner,
            ) as handle:
                handle.write(f"{line}\n")
        except OSError:
            return

    def _log_bridge_action(
        self,
        action: str,
        message: str,
        payload: dict[str, Any] | None,
        response: dict[str, Any],
    ) -> None:
        if not bridge_action_is_interesting(action):
            return
        self._append_bridge_log(
            "backend "
            f"{action} {message} "
            f"payload={payload_summary_for_log(payload)} "
            f"response={response_summary_for_log(response)}"
        )

    def _backend_steam_overlay_log_fragment(self) -> str:
        return "steam_overlay_open=unknown steam_overlay_source=backend-os-input"


def bridge_action_is_interesting(action: str) -> bool:
    return action in {
        "sounds_refresh",
        "audio_repair",
        "settings_update",
    }


def payload_summary_for_log(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    summary: dict[str, Any] = {}
    for key in ("sound_id", "volume", "playback_id"):
        if key in payload:
            summary[key] = payload[key]
    if not summary:
        summary["keys"] = sorted(payload)
    return summary


def response_summary_for_log(response: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "ok",
        "error",
        "sound_id",
        "playback_id",
        "backend",
        "route",
        "state",
        "last_error",
        "version",
    ):
        if key in response:
            summary[key] = response[key]
    sounds = response.get("sounds")
    if isinstance(sounds, list):
        summary["sounds_count"] = len(sounds)
        summary["sample_sounds"] = [
            {
                "id": sound.get("id"),
                "relative_path": sound.get("relative_path"),
            }
            for sound in sounds[:5]
            if isinstance(sound, dict)
        ]
    audio = response.get("audio")
    if isinstance(audio, dict):
        summary["audio"] = {
            "state": audio.get("state"),
            "sink_exists": audio.get("sink_exists"),
            "virtual_mic_exists": audio.get("virtual_mic_exists"),
            "default_source": audio.get("default_source"),
            "last_error": audio.get("last_error"),
        }
    player = response.get("player")
    if isinstance(player, dict):
        summary["player"] = {
            "backend": player.get("backend"),
        }
    if not summary:
        summary["keys"] = sorted(response)
    return summary


def parse_steam_deck_hid_report(data: bytes) -> dict[str, int] | None:
    for offset in (0, 1):
        # Some hidraw reads include a leading report id byte and some do not.
        if len(data) < offset + 16:
            continue
        version, report_type, report_length = struct.unpack_from("<HBB", data, offset)
        if version != STEAM_DECK_HID_REPORT_VERSION:
            continue
        if report_type != STEAM_DECK_HID_DECK_STATE_TYPE:
            continue
        packet_num = struct.unpack_from("<I", data, offset + 4)[0]
        buttons_l, buttons_h = struct.unpack_from("<II", data, offset + 8)
        report = {
            "offset": offset,
            "version": version,
            "type": report_type,
            "length": report_length,
            "packet_num": packet_num,
            "buttons_l": buttons_l,
            "buttons_h": buttons_h,
        }
        if len(data) >= offset + 56:
            left_x, raw_left_y, right_x, raw_right_y = struct.unpack_from("<hhhh", data, offset + 48)
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


def dominant_steam_deck_stick_direction(report: dict[str, int]) -> str | None:
    left_x = int(report.get("left_stick_x", 0))
    left_y = int(report.get("left_stick_y", 0))
    right_x = int(report.get("right_stick_x", 0))
    right_y = int(report.get("right_stick_y", 0))
    left_magnitude = max(abs(left_x), abs(left_y))
    right_magnitude = max(abs(right_x), abs(right_y))
    if left_magnitude < HIDRAW_STICK_NAVIGATION_THRESHOLD and right_magnitude < HIDRAW_STICK_NAVIGATION_THRESHOLD:
        return None

    # Use whichever stick is pushed farther so accidental drift on the other
    # stick does not steal overlay navigation.
    if right_magnitude > left_magnitude:
        x = right_x
        y = right_y
    else:
        x = left_x
        y = left_y

    if abs(x) >= abs(y):
        return "right" if x > 0 else "left"
    return "down" if y > 0 else "up"


def eviocgstring(number: int, length: int) -> int:
    # Linux _IOC(_IOC_READ, 'E', number, length)
    return (2 << 30) | (length << 16) | (ord("E") << 8) | number


def input_device_property(handle: Any, number: int) -> str:
    if fcntl is None:
        return ""
    buffer = bytearray(256)
    try:
        fcntl.ioctl(handle.fileno(), eviocgstring(number, len(buffer)), buffer, True)
    except OSError:
        return ""
    raw = bytes(buffer).split(b"\x00", 1)[0]
    return raw.decode("utf-8", errors="replace")


def input_device_name(handle: Any) -> str:
    return input_device_property(handle, 0x06)


def input_device_key_capabilities(handle: Any) -> frozenset[int]:
    if fcntl is None:
        return frozenset()
    buffer = bytearray((KEY_MAX + 8) // 8)
    try:
        fcntl.ioctl(
            handle.fileno(),
            eviocgstring(0x20 + EV_KEY, len(buffer)),
            buffer,
            True,
        )
    except OSError:
        return frozenset()
    return frozenset(
        code
        for code in range(KEY_MAX + 1)
        if buffer[code // 8] & (1 << (code % 8))
    )


def is_overlay_input_device_relevant(name: str, capabilities: frozenset[int]) -> bool:
    lowered = name.lower()
    if not lowered:
        return False
    if any(fragment in lowered for fragment in OVERLAY_INPUT_GRAB_NAME_EXCLUDES):
        return False
    if not any(fragment in lowered for fragment in OVERLAY_INPUT_GRAB_NAME_HINTS):
        return False
    navigation_codes = {
        BTN_SOUTH,
        BTN_TL,
        BTN_TR,
        BTN_DPAD_UP,
        BTN_DPAD_DOWN,
        BTN_DPAD_LEFT,
        BTN_DPAD_RIGHT,
    }
    hotkey_codes = set(LEGACY_L5_EVENT_CODES)
    for codes in STEAM_DECK_REAR_BUTTON_EVENT_CODES.values():
        hotkey_codes.update(codes)
    return bool(capabilities & navigation_codes) and bool(capabilities & hotkey_codes)


def make_input_device_selector(
    name: str,
    phys: str,
    uniq: str,
    path: str,
) -> str | None:
    del path  # Raw event numbers are intentionally never persisted as identity.
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
        if selector and selector in seen_selectors:
            continue
        if selector:
            seen_selectors.add(selector)
        deduplicated.append(device)
    return deduplicated


def filter_overlay_input_devices(
    devices: list[dict[str, str]],
    selector: str,
) -> list[dict[str, str]]:
    if selector == "auto":
        return devices
    return [device for device in devices if device.get("id") == selector]


def discover_overlay_input_devices() -> list[dict[str, str]]:
    try:
        event_paths = sorted(Path("/dev/input").glob("event*"))
    except OSError:
        return []

    devices: list[dict[str, str]] = []
    for path in event_paths:
        try:
            handle = path.open("rb", buffering=0)
        except OSError:
            continue
        try:
            name = input_device_name(handle)
            capabilities = input_device_key_capabilities(handle)
            if not is_overlay_input_device_relevant(name, capabilities):
                continue
            phys = input_device_property(handle, 0x07)
            uniq = input_device_property(handle, 0x08)
            path_text = str(path)
            selector = make_input_device_selector(name, phys, uniq, path_text)
            devices.append(
                {
                    "id": selector or "",
                    "name": name,
                    "path": path_text,
                    "label": f"{name} ({path.name})",
                }
            )
        finally:
            try:
                handle.close()
            except OSError:
                pass
    sorted_devices = sorted(
        devices,
        key=lambda device: (device["label"].lower(), device["path"]),
    )
    return deduplicate_overlay_input_devices(sorted_devices)


def clamp_number(value: int, minimum: int, maximum: int) -> int:
    if maximum < minimum:
        return minimum
    return max(minimum, min(maximum, value))


def clean_log_text(value: str, max_length: int = 160) -> str:
    cleaned = " ".join(value.replace("\x00", " ").split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 1] + "..."


def _input_hotkey_monitor_enabled() -> bool:
    value = os.environ.get("DECKSOUNDPAD_ENABLE_INPUT_HOTKEY", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    return os.geteuid() == 0
