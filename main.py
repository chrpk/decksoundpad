"""Decky bridge and external-overlay coordinator for DeckSoundpad."""

from __future__ import annotations

# The backend package is added to sys.path before its imports below. Keep that
# runtime setup close to the imports; it is the reason for the E402 exception.
# ruff: noqa: E402
import asyncio
import json
import os
import pwd
import socket
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
from decksoundpad.input_devices import (
    AUTO_INPUT_DEVICE,
    HIDRAW_REPORT_SIZE,
    KEY_NAMES,
    REPLAY_LAST_SOUND,
    TOGGLE_OVERLAY,
    DeviceHandles,
    classify_overlay_key_press,
    classify_steam_deck_hid_press,
    close_device_handles,
    close_quietly,
    discover_overlay_input_devices,
    dominant_steam_deck_stick_direction,
    filter_overlay_input_devices,
    is_valve_hidraw_device,
    normalize_overlay_hotkey_button,
    normalize_overlay_input_device,
    open_device_paths,
    open_nonblocking,
    parse_steam_deck_hid_report,
    read_key_presses,
    read_ready_devices,
    set_device_grab,
)
from decksoundpad.logging_setup import setup_logging
from decksoundpad.models import AudioStatus, LibraryStatus, PlayerStatus, Status
from decksoundpad.overlay_layout import SOUNDS_PER_PAGE
from decksoundpad.overlay_model import (
    TONE_ERROR,
    OverlayTab,
    build_tabs,
    clamp_cursor,
    display_library_dir,
    flip_page,
    load_recent_ids,
    move_horizontal,
    move_vertical,
    push_recent,
    save_recent_ids,
    sound_label,
    summarize_mic_status,
)
from decksoundpad.paths import ensure_app_dirs, resolve_paths, user_owner
from decksoundpad.process import decky_runtime_env, subprocess_user_kwargs
from decksoundpad.safe_files import (
    ensure_directory,
    open_regular_file,
    set_socket_metadata,
)

HOTKEY_DEBOUNCE_SECONDS = 0.45
HOTKEY_DIAGNOSTIC_PRESS_LIMIT = 80
EXTERNAL_OVERLAY_SOCKET_NAME = "external-overlay.sock"
EXTERNAL_OVERLAY_ACTION_SOCKET_NAME = "external-overlay-actions.sock"
EXTERNAL_OVERLAY_LOG_NAME = "external-overlay.log"
EXTERNAL_OVERLAY_PLAYING_POLL_SECONDS = 0.4
DIRECT_INPUT_TOGGLE_DEDUP_SECONDS = 0.55
FRONTEND_AFTER_DIRECT_DEDUP_SECONDS = 0.9
INPUT_ACTION_DEBOUNCE_SECONDS = 0.22
HIDRAW_STICK_NAVIGATION_REPEAT_SECONDS = 0.24
# The Deck controller streams a state report every few milliseconds for as long
# as the plugin runs. Letting a handful queue in the kernel (64 per reader)
# between reads cuts the monitor's wakeups several-fold; every report is still
# parsed, so no button edge is lost.
HIDRAW_READ_BATCH_SECONDS = 0.02
STEAM_DECK_HID_DIRECT_SOURCES = {"os-input", "hidraw-input"}
DIRECT_INPUT_TARGETS = (TOGGLE_OVERLAY, REPLAY_LAST_SOUND)
BRIDGE_LOG_BUFFER_LINES = 120
# Matches the backend log handlers; one previous file (.1) is kept.
PUBLIC_LOG_MAX_BYTES = 512_000
LOGGED_BRIDGE_ACTIONS = frozenset({"sounds_refresh", "audio_repair", "settings_update"})
AUTOMATIC_INPUT_DEVICE = {
    "id": AUTO_INPUT_DEVICE,
    "name": "Automatic",
    "path": "",
    "label": "Automatic (all compatible controllers)",
}


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
        self._init_bridge_state()
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

    def _init_bridge_state(self) -> None:
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
        self._external_overlay_action_stop = threading.Event()
        self._external_overlay_action_thread: threading.Thread | None = None
        self._external_overlay_action_server_socket: socket.socket | None = None
        self._external_overlay_input_grab_handles: list[tuple[str, str, Any]] = []
        self._external_overlay_input_grab_attempted = False
        self._external_overlay_evdev_stop = threading.Event()
        self._external_overlay_evdev_thread: threading.Thread | None = None
        self._external_overlay_playing_stop = threading.Event()
        self._external_overlay_playing_thread: threading.Thread | None = None
        # Loaded from disk on first use; most recently played first.
        self._external_overlay_recent_ids: list[str] | None = None
        self._input_action_last_at: dict[str, float] = {}
        # device path -> (last stick direction, time it was dispatched)
        self._hidraw_stick_state: dict[str, tuple[str | None, float]] = {}
        # Input monitors retry every few seconds; report each problem once.
        self._reported_input_problems: set[str] = set()
        self._reset_external_overlay_state("Ready")

    def _reset_external_overlay_state(self, message: str) -> None:
        with self._external_overlay_lock:
            self._external_overlay_visible = False
            self._external_overlay_sounds: list[dict[str, Any]] = []
            self._external_overlay_tabs: list[OverlayTab] = build_tabs([], [])
            self._external_overlay_tab_index = 0
            self._external_overlay_tab_key: str | None = None
            # Index into the current tab's sounds; the page follows from it.
            self._external_overlay_cursor = 0
            self._external_overlay_message = message
            self._external_overlay_message_tone = "info"
            self._external_overlay_toast: dict[str, str] | None = None
            self._external_overlay_mic = summarize_mic_status(None)
            self._external_overlay_library_dir: str | None = None
            self._external_overlay_playing_ids: frozenset[str] = frozenset()
            self._external_overlay_last_direct_toggle = 0.0

    async def _unload(self) -> None:
        if not hasattr(self, "_bridge_lifecycle_lock"):
            return  # _main failed before the bridge state existed.
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
            await asyncio.to_thread(app.close)
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

    async def set_library_folder(self, folder: str) -> dict[str, Any]:
        result = await self._call_backend(
            "library_folder",
            lambda app: app.set_library_folder(folder),
            fallback={
                "ok": False,
                "error": "backend unavailable",
                "settings": self.settings.to_dict(),
                "sounds": [],
            },
        )
        try:
            self.settings = self._backend().settings
        except Exception:
            self.settings = load_config(self.paths)
        return result

    async def play_test_sound(self) -> dict[str, Any]:
        return await self._call_backend(
            "test_sound",
            lambda app: app.play_test_sound(),
            fallback={"ok": False, "error": "backend unavailable"},
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
                dict(AUTOMATIC_INPUT_DEVICE),
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
            self._reset_external_overlay_state("Restarting DeckSoundpad")
            self._input_action_last_at.clear()
            self._hidraw_stick_state.clear()
            self._reported_input_problems.clear()
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
                if not is_running(self._input_restart_thread):
                    self._input_restart_thread = None
            self._start_healthcheck()
            self._start_external_overlay_action_server()
            with self._input_monitor_lock:
                self._start_hotkey_monitor()
                self._start_hidraw_monitor()
            self._append_bridge_log(
                "full runtime restart: bridge reinitialization finished"
            )

    def _backend(self) -> DeckSoundpadApp:
        app = getattr(self, "app", None)
        if app is not None:
            return app
        with self._backend_lock:
            if getattr(self, "app", None) is None:
                self.app = self._create_backend()
            return self.app

    def _overlay_hotkey_button(self) -> str:
        settings = getattr(self._backend(), "settings", self.settings)
        return normalize_overlay_hotkey_button(
            getattr(settings, "overlay_hotkey_button", "l5")
        )

    def _overlay_input_device(self) -> str:
        settings = getattr(self._backend(), "settings", self.settings)
        return normalize_overlay_input_device(
            getattr(settings, "overlay_input_device", AUTO_INPUT_DEVICE)
        )

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
        with self._backend_lock:
            if self._backend_start_completed or is_running(self._backend_start_thread):
                return
            self._backend_start_thread = start_daemon_thread(
                self._backend_start_worker,
                "decksoundpad-backend-start",
            )

    def _backend_start_worker(self) -> None:
        try:
            app = self._backend()
            self._append_bridge_log("backend initialization: full runtime restart")
            repair_response = app.repair_audio(
                before_restart=self._prepare_bridge_runtime_restart,
                after_restart=self._finish_bridge_runtime_restart,
            )
            self._log_bridge_action(
                "audio_repair", "startup response", None, repair_response
            )
            self._append_bridge_log("backend initialization: refresh sound library")
            library_response = app.refresh_library()
            self._log_bridge_action(
                "sounds_refresh", "startup response", None, library_response
            )
            self._backend_start_completed = True
        except Exception as exc:
            self._record_bridge_exception("backend_start_worker", exc)

    def _start_healthcheck(self) -> None:
        if not self.settings.background_healthcheck_enabled:
            self.logger.info("background healthcheck disabled")
            return
        current = self._healthcheck_stop
        if current is not None and not current.is_set():
            return
        self._healthcheck_stop = start_healthcheck_loop(self._backend())

    def _stop_healthcheck(self) -> None:
        stop = self._healthcheck_stop
        if stop is None:
            return
        stop_thread(stop, getattr(stop, "_decksoundpad_thread", None), timeout=2.0)
        self._healthcheck_stop = None

    def _start_hotkey_monitor(self) -> None:
        if not _input_hotkey_monitor_enabled():
            self._append_bridge_log(
                "Overlay OS hotkey monitor disabled by DECKSOUNDPAD_ENABLE_INPUT_HOTKEY"
            )
            return
        if is_running(self._hotkey_thread):
            return
        self._hotkey_stop.clear()
        self._hotkey_thread = start_daemon_thread(
            self._hotkey_monitor_worker,
            "decksoundpad-overlay-hotkey",
        )

    def _stop_hotkey_monitor(self) -> None:
        self._hotkey_thread = stop_thread(self._hotkey_stop, self._hotkey_thread)

    def _start_hidraw_monitor(self) -> None:
        if not _input_hotkey_monitor_enabled():
            self._append_bridge_log(
                "Steam Deck HID monitor disabled by DECKSOUNDPAD_ENABLE_INPUT_HOTKEY"
            )
            return
        if is_running(self._hidraw_thread):
            return
        self._hidraw_stop.clear()
        self._hidraw_thread = start_daemon_thread(
            self._hidraw_monitor_worker,
            "decksoundpad-steamdeck-hidraw",
        )

    def _stop_hidraw_monitor(self) -> None:
        self._hidraw_thread = stop_thread(self._hidraw_stop, self._hidraw_thread)

    def _request_input_monitor_restart(self) -> None:
        with self._input_restart_request_lock:
            if self._input_restarts_disabled:
                return
            self._input_restart_requested.set()
            if is_running(self._input_restart_thread):
                return
            self._input_restart_thread = start_daemon_thread(
                self._input_monitor_restart_coordinator,
                "decksoundpad-input-restart",
            )

    def _input_monitor_restart_coordinator(self) -> None:
        while True:
            self._input_restart_requested.clear()
            self._restart_input_monitors()
            with self._input_restart_request_lock:
                if (
                    self._input_restart_requested.is_set()
                    and not self._input_restarts_disabled
                ):
                    continue
                self._input_restart_thread = None
                return

    def _stop_input_monitor_restart_coordinator(self) -> None:
        with self._input_restart_request_lock:
            self._input_restarts_disabled = True
            self._input_restart_requested.clear()
            thread = self._input_restart_thread
        stop_thread(None, thread)

    def _restart_input_monitors(self) -> None:
        with self._input_monitor_lock:
            self._release_external_overlay_input_grab()
            self._stop_hotkey_monitor()
            self._stop_hidraw_monitor()
            with self._input_restart_request_lock:
                if self._input_restarts_disabled:
                    return
            self._reported_input_problems.clear()
            self._start_hotkey_monitor()
            self._start_hidraw_monitor()
            self._sync_external_overlay_input_grab()

    def _external_overlay_socket_path(self) -> Path:
        return self._external_overlay_runtime_dir() / EXTERNAL_OVERLAY_SOCKET_NAME

    def _external_overlay_action_socket_path(self) -> Path:
        return (
            self._external_overlay_runtime_dir() / EXTERNAL_OVERLAY_ACTION_SOCKET_NAME
        )

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
        return (
            stat_result.st_uid,
            stat_result.st_gid,
            passwd.pw_name,
            self.paths.user_home,
        )

    def _external_overlay_owner(self) -> tuple[int, int] | None:
        """Return the Steam user's ownership pair when the bridge can apply it."""

        identity = self._external_overlay_target_identity()
        if identity is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
            return None
        return identity[0], identity[1]

    def _external_overlay_user_runtime_dir(self) -> Path | None:
        identity = self._external_overlay_target_identity()
        if identity is None:
            return None
        user_runtime = Path(f"/run/user/{identity[0]}")
        return user_runtime if user_runtime.exists() else None

    def _external_overlay_runtime_dir(self) -> Path:
        # The GTK overlay must share the Steam user's runtime directory so it can
        # reach the same X11/Gamescope sockets as the active session.
        user_runtime = self._external_overlay_user_runtime_dir()
        if user_runtime is not None:
            return user_runtime / "decksoundpad"
        return self.paths.runtime_dir / "external-overlay"

    def _external_overlay_env(self) -> dict[str, str]:
        env = decky_runtime_env(os.environ)
        identity = self._external_overlay_target_identity()
        if identity is not None:
            _uid, _gid, username, home = identity
            env["HOME"] = str(home)
            env["USER"] = username
            env["LOGNAME"] = username
            user_runtime = self._external_overlay_user_runtime_dir()
            if user_runtime is not None:
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

    def _start_external_overlay_action_server(self) -> None:
        thread = self._external_overlay_action_thread
        if is_running(thread):
            if self._external_overlay_action_stop.is_set():
                thread.join(timeout=2.0)
            if thread.is_alive():
                raise RuntimeError(
                    "previous external overlay action server is still stopping"
                )
        stop = threading.Event()
        self._external_overlay_action_stop = stop
        self._external_overlay_action_thread = start_daemon_thread(
            self._external_overlay_action_server_worker,
            "decksoundpad-overlay-actions",
            stop,
        )

    def _stop_external_overlay_action_server(self) -> bool:
        self._external_overlay_action_stop.set()
        server = self._external_overlay_action_server_socket
        if server is not None:
            close_quietly(server)
        # Wake a worker blocked in accept() so it notices the stop flag promptly.
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.05)
                client.connect(str(self._external_overlay_action_socket_path()))
        except OSError:
            pass
        thread = stop_thread(None, self._external_overlay_action_thread, timeout=1.5)
        if thread is not None:
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
            self._append_bridge_log(
                f"external overlay action socket prepare failed: {exc}"
            )
            return

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._external_overlay_action_server_socket = server
        try:
            server.bind(str(socket_path))
            self._prepare_external_overlay_socket_file(socket_path, mode=0o600)
            server.listen(8)
            server.settimeout(0.5)
            self._append_bridge_log(
                f"external overlay action socket listening path={socket_path}"
            )
            while not stop.is_set():
                try:
                    client, _addr = server.accept()
                except TimeoutError:
                    continue
                with client:
                    client.settimeout(0.5)
                    try:
                        payload = client.recv(64 * 1024)
                    except TimeoutError:
                        continue
                for line in payload.splitlines():
                    try:
                        command = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        self._append_bridge_log(
                            f"external overlay action invalid json: {exc}"
                        )
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
            socket_path.unlink(missing_ok=True)

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

        if command_type not in {"select", "tab"}:
            return

        try:
            requested_index = int(command.get("index", 0))
        except (TypeError, ValueError):
            requested_index = 0
        play = bool(command.get("play"))

        with self._external_overlay_lock:
            if not self._external_overlay_visible:
                return
            if command_type == "tab":
                self._select_external_overlay_tab(requested_index)
                self._append_bridge_log(
                    f"external overlay touch tab index={self._external_overlay_tab_index}"
                )
                self._send_external_overlay_state()
                return
            page_sounds = self._external_overlay_page_sounds()
            if not page_sounds:
                return
            page_start = self._external_overlay_page() * SOUNDS_PER_PAGE
            self._external_overlay_cursor = page_start + clamp_number(
                requested_index,
                0,
                len(page_sounds) - 1,
            )
            self._append_bridge_log(
                "external overlay touch select "
                f"index={self._external_overlay_cursor - page_start} play={play}"
            )
            if play:
                self._play_external_overlay_selection(close=True)
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
            output = clean_log_text(
                " ".join(str(part or "") for part in (exc.stdout, exc.stderr)), 240
            )
            raise RuntimeError(
                f"external overlay runtime check timed out: {output}"
            ) from exc

        if result.returncode == 0:
            return

        output = clean_log_text(
            "\n".join(part for part in (result.stdout, result.stderr) if part), 320
        )
        if not output:
            output = (
                f"Gtk.init_check failed display={env.get('DISPLAY', '<unset>')} "
                f"xauthority={env.get('XAUTHORITY', '<unset>')} user={env.get('USER', '<unset>')}"
            )
        raise RuntimeError(f"external overlay runtime check failed: {output}")

    def _external_overlay_log_tail(self, lines: int = 12) -> str:
        try:
            content = (
                self._external_overlay_log_file()
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()
            )
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
            if self._external_overlay_process is not None:
                exit_error = self._external_overlay_process_exit_error()
                if exit_error is None:
                    return
                self._append_bridge_log(f"{exit_error}; restarting")

            socket_path = self._external_overlay_socket_path()
            socket_path.unlink(missing_ok=True)
            self._prepare_external_overlay_runtime_dir(socket_path.parent)
            env = self._external_overlay_env()
            python = env.get("DECKSOUNDPAD_OVERLAY_PYTHON") or "/usr/bin/python3"
            self._check_external_overlay_runtime(python, env)
            log_file = self._external_overlay_log_file()
            owner = self._external_overlay_owner()
            ensure_directory(log_file.parent, mode=0o750, owner=owner)
            # The overlay appends for its whole lifetime, so trim between runs.
            rotate_large_log(log_file)
            args = [
                python,
                str(self._external_overlay_script()),
                "--socket",
                str(socket_path),
                "--actions-socket",
                str(self._external_overlay_action_socket_path()),
                "--log",
                str(log_file),
            ]
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
            self._external_overlay_playing_stop.set()
            process = self._external_overlay_process
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
        if (
            self._external_overlay_input_grab_handles
            or self._external_overlay_input_grab_attempted
        ):
            return
        self._external_overlay_input_grab_attempted = True
        devices = filter_overlay_input_devices(
            discover_overlay_input_devices(),
            self._overlay_input_device(),
        )
        grabbed: list[tuple[str, str, Any]] = []
        for device in devices:
            path_text = device["path"]
            name = device["name"]
            try:
                handle = open_nonblocking(path_text)
            except OSError:
                continue
            try:
                set_device_grab(handle, True)
            except OSError as exc:
                self._append_bridge_log(
                    f"external overlay input grab failed device={path_text} name={name!r}: {exc}"
                )
                close_quietly(handle)
                continue
            grabbed.append((path_text, name, handle))

        self._external_overlay_input_grab_handles = grabbed
        if grabbed:
            devices_text = ",".join(
                f"{path}:{name or 'unknown'}" for path, name, _handle in grabbed
            )
            self._append_bridge_log(
                f"external overlay input grab enabled devices={devices_text}"
            )
            self._start_external_overlay_evdev_reader()
        else:
            self._append_bridge_log(
                "external overlay input grab found no gamepad event devices"
            )

    def _start_external_overlay_evdev_reader(self) -> None:
        if is_running(self._external_overlay_evdev_thread):
            return
        stop = threading.Event()
        self._external_overlay_evdev_stop = stop
        self._external_overlay_evdev_thread = start_daemon_thread(
            self._external_overlay_evdev_worker,
            "decksoundpad-overlay-evdev",
            stop,
        )

    def _external_overlay_evdev_worker(self, stop: threading.Event) -> None:
        self._append_bridge_log("external overlay selected evdev reader started")
        while not stop.is_set() and self._external_overlay_visible:
            handles = [
                (path, handle)
                for path, _name, handle in self._external_overlay_input_grab_handles
            ]
            if not handles:
                break
            try:
                for device_path, code in read_key_presses(
                    handles, timeout=0.5, stop=stop
                ):
                    self._handle_external_overlay_evdev_press(code, device_path, stop)
            except (OSError, ValueError):
                # ValueError means a handle was closed by a concurrent grab release.
                break
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
            self._dispatch_overlay_input(
                self._classify_overlay_key_press(code),
                "evdev-grab",
                device_path,
            )

    def _release_external_overlay_input_grab(self) -> None:
        with self._external_overlay_lock:
            self._external_overlay_evdev_stop.set()
            thread = self._external_overlay_evdev_thread
            handles = self._external_overlay_input_grab_handles
            self._external_overlay_input_grab_handles = []
            self._external_overlay_input_grab_attempted = False
        for path, name, handle in handles:
            try:
                set_device_grab(handle, False)
            except OSError as exc:
                self._append_bridge_log(
                    f"external overlay input grab release failed device={path} name={name!r}: {exc}"
                )
            close_quietly(handle)
        if handles:
            self._append_bridge_log("external overlay input grab released")
        thread = stop_thread(None, thread, timeout=1.0)
        with self._external_overlay_lock:
            if thread is None:
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
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(0.35)
                    client.connect(str(self._external_overlay_socket_path()))
                    client.sendall(encoded)
                    return
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
            dedup_window = (
                DIRECT_INPUT_TOGGLE_DEDUP_SECONDS
                if is_direct_input
                else FRONTEND_AFTER_DIRECT_DEDUP_SECONDS
            )
            if now - self._external_overlay_last_direct_toggle < dedup_window:
                # The same rear-button press can arrive through hidraw and evdev
                # (and other bridges); keep the first toggle and ignore the echoes.
                self._append_bridge_log(
                    f"external overlay duplicate {'direct' if is_direct_input else 'frontend'} "
                    f"toggle ignored visible={self._external_overlay_visible} source={source}"
                )
                return {**self._external_overlay_toggle_response(), "deduped": True}

            previous_visible = self._external_overlay_visible
            self._external_overlay_visible = not self._external_overlay_visible
            self._set_external_overlay_message("")
            try:
                if self._external_overlay_visible:
                    self._reload_external_overlay_sounds()
                    self._refresh_external_overlay_status()
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
            return self._external_overlay_toggle_response()

    def _external_overlay_toggle_response(self) -> dict[str, Any]:
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

            count = len(self._external_overlay_tab().sounds)
            cursor = self._external_overlay_cursor
            if action == "hide":
                self._external_overlay_visible = False
            elif action in {"next", "right"}:
                self._external_overlay_cursor = move_horizontal(cursor, count, 1)
            elif action in {"prev", "left"}:
                self._external_overlay_cursor = move_horizontal(cursor, count, -1)
            elif action == "down":
                self._external_overlay_cursor = move_vertical(cursor, count, 1)
            elif action == "up":
                self._external_overlay_cursor = move_vertical(cursor, count, -1)
            elif action == "page_next":
                self._flip_external_overlay_page(1)
            elif action == "page_prev":
                self._flip_external_overlay_page(-1)
            elif action == "play":
                self._play_external_overlay_selection(close=True)
            elif action == "play_stay":
                self._play_external_overlay_selection(close=False)
            elif action == "stop":
                self._stop_external_overlay_sounds()
            else:
                return {
                    "ok": False,
                    "visible": self._external_overlay_visible,
                    "error": f"unknown action: {safe_action}",
                }

            self._send_external_overlay_state()
            return {
                "ok": True,
                "visible": self._external_overlay_visible,
                "action": safe_action,
                "tab_index": self._external_overlay_tab_index,
                "page": self._external_overlay_page(),
                "selected_index": self._external_overlay_cursor % SOUNDS_PER_PAGE,
            }

    def _reload_external_overlay_sounds(self) -> None:
        response = self._backend().list_sounds()
        sounds = response.get("sounds") if isinstance(response, dict) else None
        self._external_overlay_sounds = [
            sound for sound in sounds or [] if isinstance(sound, dict)
        ]
        self._external_overlay_tabs = build_tabs(
            self._external_overlay_sounds,
            self._external_overlay_recent(),
        )
        keys = [tab.key for tab in self._external_overlay_tabs]
        # Reopen on the tab the user left; the first open starts on Recent.
        previous_key = self._external_overlay_tab_key
        self._external_overlay_tab_index = (
            keys.index(previous_key) if previous_key in keys else 0
        )
        self._external_overlay_tab_key = keys[self._external_overlay_tab_index]
        self._external_overlay_cursor = clamp_cursor(
            self._external_overlay_cursor,
            len(self._external_overlay_tab().sounds),
        )

    def _refresh_external_overlay_status(self) -> None:
        backend = self._backend()
        try:
            status = backend.quick_status()
        except Exception as exc:
            self._append_bridge_log(f"external overlay status unavailable: {exc}")
            status = None
        self._external_overlay_mic = summarize_mic_status(status)
        self._external_overlay_library_dir = display_library_dir(
            status, self.paths.user_home
        )
        playing = backend.playing_sound_ids()
        if playing is not None:
            self._external_overlay_playing_ids = playing

    def _external_overlay_tab(self) -> OverlayTab:
        tabs = self._external_overlay_tabs
        return tabs[clamp_number(self._external_overlay_tab_index, 0, len(tabs) - 1)]

    def _external_overlay_page(self) -> int:
        cursor = clamp_cursor(
            self._external_overlay_cursor, len(self._external_overlay_tab().sounds)
        )
        return cursor // SOUNDS_PER_PAGE

    def _external_overlay_page_sounds(self) -> tuple[dict[str, Any], ...]:
        start = self._external_overlay_page() * SOUNDS_PER_PAGE
        return self._external_overlay_tab().sounds[start : start + SOUNDS_PER_PAGE]

    def _flip_external_overlay_page(self, direction: int) -> None:
        self._external_overlay_tab_index, self._external_overlay_cursor = flip_page(
            self._external_overlay_tabs,
            self._external_overlay_tab_index,
            self._external_overlay_cursor,
            direction,
        )
        self._external_overlay_tab_key = self._external_overlay_tab().key

    def _select_external_overlay_tab(self, index: int) -> None:
        offset = self._external_overlay_cursor % SOUNDS_PER_PAGE
        self._external_overlay_tab_index = clamp_number(
            index, 0, len(self._external_overlay_tabs) - 1
        )
        tab = self._external_overlay_tab()
        self._external_overlay_tab_key = tab.key
        # Land on the same grid position on the tab's first page.
        self._external_overlay_cursor = clamp_cursor(offset, len(tab.sounds))

    def _set_external_overlay_message(self, message: str, tone: str = "info") -> None:
        self._external_overlay_message = message
        self._external_overlay_message_tone = tone

    def _external_overlay_recent(self) -> list[str]:
        if self._external_overlay_recent_ids is None:
            self._external_overlay_recent_ids = load_recent_ids(
                self.paths.overlay_recent_file
            )
        return self._external_overlay_recent_ids

    def _remember_recent_sound(self, sound_id: str) -> None:
        recent = push_recent(self._external_overlay_recent(), sound_id)
        self._external_overlay_recent_ids = recent
        try:
            save_recent_ids(
                self.paths.overlay_recent_file, recent, owner=user_owner(self.paths)
            )
        except OSError as exc:
            self._append_bridge_log(f"external overlay recent sounds not saved: {exc}")

    def _play_external_overlay_selection(self, *, close: bool) -> None:
        sounds = self._external_overlay_tab().sounds
        if not sounds:
            self._set_external_overlay_message("No sound selected", TONE_ERROR)
            return
        sound = sounds[clamp_cursor(self._external_overlay_cursor, len(sounds))]
        self._play_external_overlay_sound(sound, close=close)

    def _play_external_overlay_sound(
        self, sound: dict[str, Any], *, close: bool
    ) -> bool:
        """Play ``sound``; closing (or playing while hidden) confirms with a toast."""

        sound_id = sound.get("id")
        label = sound_label(sound)
        if not isinstance(sound_id, str):
            self._set_external_overlay_message("No sound selected", TONE_ERROR)
            return False
        response = self._backend().play_sound({"sound_id": sound_id, "volume": None})
        if not response.get("ok"):
            error = clean_log_text(
                f"Could not play {label}: {response.get('error') or 'playback failed'}",
                120,
            )
            if self._external_overlay_visible:
                self._set_external_overlay_message(error, TONE_ERROR)
            else:
                self._external_overlay_toast = {"text": error, "tone": TONE_ERROR}
            return False

        self._remember_recent_sound(sound_id)
        # Mark the tile now; the playing watch clears it when the sound ends.
        self._external_overlay_playing_ids = self._external_overlay_playing_ids | {
            sound_id
        }
        if close or not self._external_overlay_visible:
            self._external_overlay_visible = False
            self._external_overlay_toast = {"text": label, "tone": "play"}
        else:
            self._set_external_overlay_message(f"Playing {label}")
        return True

    def _stop_external_overlay_sounds(self) -> None:
        try:
            self._backend().stop_all_sounds()
        except Exception as exc:
            self._record_bridge_exception("stop overlay sounds", exc)
            self._set_external_overlay_message("Could not stop sounds", TONE_ERROR)
            return
        self._external_overlay_playing_ids = frozenset()
        self._set_external_overlay_message("Stopped all sounds")

    def _replay_last_external_overlay_sound(self) -> dict[str, Any]:
        with self._external_overlay_lock:
            if not self._external_overlay_visible:
                # Keep the open overlay's tabs stable; refresh them only while hidden.
                self._reload_external_overlay_sounds()
            by_id = {sound.get("id"): sound for sound in self._external_overlay_sounds}
            sound = next(
                (
                    by_id[sound_id]
                    for sound_id in self._external_overlay_recent()
                    if sound_id in by_id
                ),
                None,
            )
            if sound is None:
                played = False
                if self._external_overlay_visible:
                    self._set_external_overlay_message("Nothing to replay yet")
                else:
                    self._external_overlay_toast = {
                        "text": "Nothing to replay yet",
                        "tone": "info",
                    }
            else:
                played = self._play_external_overlay_sound(sound, close=False)
            try:
                self._send_external_overlay_state()
            except Exception as exc:
                # The sound already played; only the confirmation is lost, so
                # keep this to one log line instead of a traceback per press.
                self._append_bridge_log(
                    f"replay confirmation not shown: {clean_log_text(str(exc))}"
                )
            response: dict[str, Any] = {
                "ok": played,
                "visible": self._external_overlay_visible,
                "sound_id": sound.get("id") if sound is not None else None,
            }
            if sound is None:
                response["error"] = "no recent sound"
            return response

    def _send_external_overlay_state(self) -> None:
        tab = self._external_overlay_tab()
        cursor = clamp_cursor(self._external_overlay_cursor, len(tab.sounds))
        hotkey_button = self._overlay_hotkey_button()
        command: dict[str, Any] = {
            "type": "state",
            "visible": self._external_overlay_visible,
            "sounds": [
                {
                    "id": sound.get("id"),
                    "display_name": sound.get("display_name"),
                    "relative_path": sound.get("relative_path"),
                }
                for sound in self._external_overlay_page_sounds()
            ],
            "selected_index": cursor % SOUNDS_PER_PAGE,
            "page": cursor // SOUNDS_PER_PAGE,
            "page_count": tab.page_count,
            "total_count": len(self._external_overlay_sounds),
            "tabs": [
                {"label": candidate.label, "count": len(candidate.sounds)}
                for candidate in self._external_overlay_tabs
            ],
            "tab_index": self._external_overlay_tab_index,
            "playing_ids": sorted(self._external_overlay_playing_ids),
            "message": self._external_overlay_message,
            "message_tone": self._external_overlay_message_tone,
            "mic": dict(self._external_overlay_mic),
            "library_dir": self._external_overlay_library_dir,
            "overlay_hotkey_button": hotkey_button.upper(),
            # R5 replays the last sound unless it is the overlay button.
            "replay_button": None if hotkey_button == "r5" else "R5",
        }
        toast, self._external_overlay_toast = self._external_overlay_toast, None
        if toast is not None and not self._external_overlay_visible:
            command["toast"] = toast
        if self._external_overlay_visible:
            # Grab before showing state so the game does not also receive the
            # button press that opens and navigates the overlay.
            self._sync_external_overlay_input_grab()
        self._send_external_overlay_command(command)
        if not self._external_overlay_visible:
            self._sync_external_overlay_input_grab()
        self._sync_external_overlay_playing_watch()

    def _sync_external_overlay_playing_watch(self) -> None:
        """Poll for finished sounds only while the overlay shows something playing."""

        with self._external_overlay_lock:
            if not (
                self._external_overlay_visible and self._external_overlay_playing_ids
            ):
                self._external_overlay_playing_stop.set()
                return
            if (
                is_running(self._external_overlay_playing_thread)
                and not self._external_overlay_playing_stop.is_set()
            ):
                return
            stop = threading.Event()
            self._external_overlay_playing_stop = stop
            self._external_overlay_playing_thread = start_daemon_thread(
                self._external_overlay_playing_worker,
                "decksoundpad-overlay-playing",
                stop,
            )

    def _external_overlay_playing_worker(self, stop: threading.Event) -> None:
        while not stop.wait(EXTERNAL_OVERLAY_PLAYING_POLL_SECONDS):
            try:
                playing = self._backend().playing_sound_ids()
            except Exception as exc:
                self._record_bridge_exception("poll overlay playing sounds", exc)
                return
            if playing is None:
                continue
            with self._external_overlay_lock:
                if stop.is_set() or not self._external_overlay_visible:
                    return
                if playing == self._external_overlay_playing_ids:
                    continue
                self._external_overlay_playing_ids = playing
                try:
                    self._send_external_overlay_state()
                except Exception as exc:
                    self._record_bridge_exception("refresh overlay playing sounds", exc)
                    return

    def _monitor_input_devices(
        self,
        name: str,
        device_glob: str,
        stop: threading.Event,
        open_devices: Callable[[], DeviceHandles],
        poll: Callable[[DeviceHandles], None],
    ) -> None:
        """Keep devices open and poll them until ``stop``, reopening after read errors."""

        self._append_bridge_log(f"{name} starting")
        reported_missing = False
        while not stop.is_set():
            handles = open_devices()
            if not handles:
                # Devices can be grabbed by Steam or appear later, so keep
                # retrying, but only log the missing state once per transition
                # instead of flooding the bridge log every poll cycle.
                if not reported_missing:
                    reported_missing = True
                    self._append_bridge_log(
                        f"{name} found no readable {device_glob} devices; "
                        "retrying quietly until one becomes available"
                    )
                stop.wait(5.0)
                continue
            reported_missing = False
            self._append_bridge_log(
                f"{name} opened devices=" + ",".join(path for path, _handle in handles)
            )
            try:
                while not stop.is_set():
                    poll(handles)
            except OSError as exc:
                self._append_bridge_log(f"{name} read failed: {exc}")
                stop.wait(1.0)
            finally:
                close_device_handles(handles)
        self._append_bridge_log(f"{name} stopped")

    def _hidraw_monitor_worker(self) -> None:
        if self._overlay_input_device() != AUTO_INPUT_DEVICE:
            self._append_bridge_log(
                "Steam Deck HID monitor disabled: explicit evdev input device selected"
            )
            return
        previous_buttons: dict[str, int] = {}

        def poll(handles: DeviceHandles) -> None:
            for device_path, data in read_ready_devices(
                handles, size=HIDRAW_REPORT_SIZE, timeout=1.0
            ):
                report = parse_steam_deck_hid_report(data)
                if report is not None:
                    self._handle_steam_deck_hid_report(
                        report, device_path, previous_buttons
                    )
            self._hidraw_stop.wait(HIDRAW_READ_BATCH_SECONDS)

        self._monitor_input_devices(
            "Steam Deck HID monitor",
            "/dev/hidraw*",
            self._hidraw_stop,
            self._open_hidraw_devices,
            poll,
        )

    def _handle_steam_deck_hid_report(
        self,
        report: dict[str, int],
        device_path: str,
        previous_buttons: dict[str, int],
    ) -> None:
        buttons_l = report["buttons_l"]
        buttons_h = report["buttons_h"]
        buttons = buttons_l | (buttons_h << 32)
        previous = previous_buttons.get(device_path)
        previous_buttons[device_path] = buttons
        if previous is None:
            # The first report is a baseline; only edge transitions after that
            # should trigger actions.
            self._append_bridge_log(
                "Steam Deck HID state report detected "
                f"device={device_path} offset={report['offset']} "
                f"buttons_l=0x{buttons_l:08x} buttons_h=0x{buttons_h:08x}"
            )
            return

        pressed = buttons & ~previous
        if pressed:
            hotkey_button = self._overlay_hotkey_button()
            target = classify_steam_deck_hid_press(pressed, hotkey_button)
            if target in DIRECT_INPUT_TARGETS:
                self._append_bridge_log(
                    f"Steam Deck HID {target} press hotkey={hotkey_button.upper()} "
                    f"device={device_path} buttons_l=0x{buttons_l:08x} buttons_h=0x{buttons_h:08x}"
                )
                self._dispatch_overlay_input(target, "hidraw-input", device_path)
                return
            self._dispatch_overlay_input(target, "hidraw-input", device_path)
        if self._external_overlay_visible:
            self._handle_hidraw_overlay_sticks(report, device_path)

    def _open_hidraw_devices(self) -> DeviceHandles:
        if self._overlay_input_device() != AUTO_INPUT_DEVICE:
            return []
        try:
            hidraw_paths = [
                path
                for path in sorted(Path("/dev").glob("hidraw*"))
                if is_valve_hidraw_device(path)
            ]
        except OSError as exc:
            self._append_bridge_log_once(f"Steam Deck HID device scan failed: {exc}")
            return []
        return open_device_paths(
            hidraw_paths,
            lambda path, exc: self._append_bridge_log_once(
                f"Steam Deck HID cannot open {path}: {exc}"
            ),
        )

    def _classify_overlay_key_press(self, code: int) -> str | None:
        return classify_overlay_key_press(
            code,
            self._overlay_hotkey_button(),
            include_legacy_l5=self._overlay_input_device() == AUTO_INPUT_DEVICE,
        )

    def _dispatch_overlay_input(
        self, target: str | None, source: str, device_path: str
    ) -> None:
        """Route a classified press from any input path to the overlay."""

        if target == TOGGLE_OVERLAY:
            self._handle_overlay_direct_hotkey(source)
        elif target == REPLAY_LAST_SOUND:
            self._handle_replay_last_sound(source, device_path)
        elif target is not None and self._external_overlay_visible:
            self._handle_debounced_overlay_action(target, source, device_path)

    def _debounce_input(self, key: str) -> bool:
        """Return True, and record the time, unless ``key`` fired within the debounce window."""

        with self._external_overlay_lock:
            now = time.monotonic()
            if (
                now - self._input_action_last_at.get(key, 0.0)
                < INPUT_ACTION_DEBOUNCE_SECONDS
            ):
                return False
            self._input_action_last_at[key] = now
            return True

    def _handle_debounced_overlay_action(
        self,
        action: str,
        source: str,
        device_path: str,
    ) -> bool:
        detail = f"source={source} device={device_path} action={action}"
        if not self._debounce_input(action):
            self._append_bridge_log(f"Overlay input action debounced {detail}")
            return False
        self._append_bridge_log(f"Overlay input action {detail}")
        try:
            response = self._handle_external_overlay_input(action)
        except Exception as exc:
            self._record_bridge_exception(
                f"handle overlay action {action} from {source}", exc
            )
            return False
        self._append_bridge_log(
            "Overlay input action handled "
            f"source={source} action={action} visible={bool(response.get('visible'))}"
        )
        return True

    def _handle_hidraw_overlay_sticks(
        self, report: dict[str, int], device_path: str
    ) -> None:
        direction = dominant_steam_deck_stick_direction(report)
        previous_direction, previous_at = self._hidraw_stick_state.get(
            device_path, (None, 0.0)
        )
        if direction is None:
            self._hidraw_stick_state[device_path] = (None, previous_at)
            return

        now = time.monotonic()
        if (
            direction == previous_direction
            and now - previous_at < HIDRAW_STICK_NAVIGATION_REPEAT_SECONDS
        ):
            return

        self._hidraw_stick_state[device_path] = (direction, now)
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
            self._record_bridge_exception(
                f"handle Steam Deck HID stick direction {direction}", exc
            )

    def _hotkey_monitor_worker(self) -> None:
        last_toggle_at = 0.0
        seen_press_codes: set[tuple[str, int]] = set()

        def poll(handles: DeviceHandles) -> None:
            nonlocal last_toggle_at
            for device_path, code in read_key_presses(handles, timeout=1.0):
                key_name = KEY_NAMES.get(code, "unknown")
                key = (device_path, code)
                if (
                    len(seen_press_codes) < HOTKEY_DIAGNOSTIC_PRESS_LIMIT
                    and key not in seen_press_codes
                ):
                    seen_press_codes.add(key)
                    self._append_bridge_log(
                        "Overlay OS hotkey observed key press "
                        f"device={device_path} code={code} hex=0x{code:x} name={key_name}"
                    )
                target = self._classify_overlay_key_press(code)
                if target == TOGGLE_OVERLAY:
                    self._append_bridge_log(
                        "Overlay OS hotkey press "
                        f"button={self._overlay_hotkey_button().upper()} device={device_path} "
                        f"code={code} hex=0x{code:x} name={key_name}"
                    )
                    now = time.monotonic()
                    if now - last_toggle_at < HOTKEY_DEBOUNCE_SECONDS:
                        continue
                    last_toggle_at = now
                self._dispatch_overlay_input(target, "os-input", device_path)

        self._monitor_input_devices(
            "Overlay OS hotkey monitor",
            "/dev/input/event*",
            self._hotkey_stop,
            self._open_input_event_devices,
            poll,
        )

    def _open_input_event_devices(self) -> DeviceHandles:
        selector = self._overlay_input_device()
        devices = filter_overlay_input_devices(
            discover_overlay_input_devices(), selector
        )
        if selector != AUTO_INPUT_DEVICE and not devices:
            self._append_bridge_log_once(
                f"Configured overlay input device unavailable: {selector}"
            )
        return open_device_paths(
            (device["path"] for device in devices),
            lambda path, exc: self._append_bridge_log_once(
                f"Overlay OS hotkey cannot open {path}: {exc}"
            ),
        )

    def _handle_overlay_direct_hotkey(self, source: str) -> None:
        hotkey_button = self._overlay_hotkey_button().upper()
        self._append_bridge_log(
            f"{hotkey_button} overlay shortcut detected source={source}"
        )
        try:
            response = self._toggle_external_overlay({"source": source})
        except Exception as exc:
            self._record_bridge_exception(
                f"handle {hotkey_button} overlay hotkey source={source}",
                exc,
            )
            return
        self._append_bridge_log(
            "Overlay direct hotkey handled by backend "
            f"button={hotkey_button} source={source} "
            f"visible={bool(response.get('visible'))} sounds_count={response.get('sounds_count', 0)}"
        )

    def _handle_replay_last_sound(self, source: str, device_path: str) -> None:
        detail = f"source={source} device={device_path}"
        if not self._debounce_input(REPLAY_LAST_SOUND):
            self._append_bridge_log(f"R5 replay last sound debounced {detail}")
            return
        self._append_bridge_log(f"R5 replay last sound detected {detail}")
        try:
            response = self._replay_last_external_overlay_sound()
        except Exception as exc:
            self._record_bridge_exception(
                f"handle R5 replay last sound source={source}", exc
            )
            return
        self._append_bridge_log(
            "R5 replay last sound handled "
            f"source={source} ok={bool(response.get('ok'))} "
            f"visible={bool(response.get('visible'))} sound_id={response.get('sound_id')}"
        )

    def _fallback_status(self, last_error: str) -> dict[str, Any]:
        settings = getattr(self, "settings", None)
        status = Status(
            backend_running=False,
            audio=AudioStatus(last_error=last_error, state="offline"),
            player=PlayerStatus(backend=None),
            library=LibraryStatus(count=0),
        ).to_dict()
        status["version"] = __version__
        status["mic_passthrough_enabled"] = bool(
            getattr(settings, "mic_passthrough_enabled", False)
        )
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
        details = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).strip()
        self._append_bridge_log(message)
        for line in details.splitlines()[-12:]:
            self._append_bridge_log(line)

    def _append_bridge_log(self, line: str) -> None:
        errors = getattr(self, "_bridge_errors", None)
        if errors is None:
            errors = []
            self._bridge_errors = errors
        entry = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}"
        errors.append(entry)
        if len(errors) > BRIDGE_LOG_BUFFER_LINES:
            del errors[:-BRIDGE_LOG_BUFFER_LINES]
        self._write_public_bridge_log(entry)

    def _append_bridge_log_once(self, line: str) -> None:
        """Log ``line`` unless it was already reported since the last input restart."""

        reported = getattr(self, "_reported_input_problems", None)
        if reported is not None:
            if line in reported:
                return
            reported.add(line)
        self._append_bridge_log(line)

    def _write_public_bridge_log(self, line: str) -> None:
        paths = getattr(self, "paths", None)
        if paths is None:
            return
        try:
            owner = user_owner(paths)
            ensure_directory(paths.public_log_dir, mode=0o750, owner=owner)
            rotate_large_log(paths.public_bridge_log_file)
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
        if action not in LOGGED_BRIDGE_ACTIONS:
            return
        self._append_bridge_log(
            "backend "
            f"{action} {message} "
            f"payload={payload_summary_for_log(payload)} "
            f"response={response_summary_for_log(response)}"
        )


def payload_summary_for_log(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    summary = {
        key: payload[key]
        for key in ("sound_id", "volume", "playback_id")
        if key in payload
    }
    return summary or {"keys": sorted(payload)}


def response_summary_for_log(response: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        key: response[key]
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
        )
        if key in response
    }
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
            key: audio.get(key)
            for key in (
                "state",
                "sink_exists",
                "virtual_mic_exists",
                "default_source",
                "last_error",
            )
        }
    player = response.get("player")
    if isinstance(player, dict):
        summary["player"] = {"backend": player.get("backend")}
    return summary or {"keys": sorted(response)}


def is_running(thread: threading.Thread | None) -> bool:
    return thread is not None and thread.is_alive()


def start_daemon_thread(
    target: Callable[..., None], name: str, *args: Any
) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    thread.start()
    return thread


def stop_thread(
    stop: threading.Event | None,
    thread: threading.Thread | None,
    *,
    timeout: float | None = None,
) -> threading.Thread | None:
    """Signal ``stop`` and join ``thread``; return the thread only if it is still alive."""

    if stop is not None:
        stop.set()
    if is_running(thread) and thread is not threading.current_thread():
        thread.join(timeout)
    return thread if is_running(thread) else None


def clamp_number(value: int, minimum: int, maximum: int) -> int:
    if maximum < minimum:
        return minimum
    return max(minimum, min(maximum, value))


def rotate_large_log(path: Path) -> None:
    """Move ``path`` to ``path.1`` once it outgrows ``PUBLIC_LOG_MAX_BYTES``."""

    try:
        if path.stat().st_size <= PUBLIC_LOG_MAX_BYTES:
            return
        os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        return


def clean_log_text(value: str, max_length: int = 160) -> str:
    cleaned = " ".join(value.replace("\x00", " ").split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 1] + "..."


def _input_hotkey_monitor_enabled() -> bool:
    """Return whether optional /dev/input hotkey monitoring should start.

    Decky runs a plugin as the host user unless the plugin requests the ``root``
    flag, and DeckSoundpad deliberately does not. Gating on ``os.geteuid() == 0``
    therefore disabled the overlay hotkeys on every normal install. Monitoring is
    opportunistic instead: start the readers for every user and let device-open
    failures fall back quietly. Set ``DECKSOUNDPAD_ENABLE_INPUT_HOTKEY=0`` to opt
    out explicitly.
    """

    value = os.environ.get("DECKSOUNDPAD_ENABLE_INPUT_HOTKEY", "").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    return True
