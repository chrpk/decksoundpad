from __future__ import annotations

import asyncio
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
from pathlib import Path
from typing import Any, Callable

try:
    import decky
except ImportError:  # Local development fallback.
    import logging

    class _DeckyFallback:
        DECKY_USER_HOME = str(Path.home())
        DECKY_PLUGIN_DIR = str(Path(__file__).resolve().parent)
        DECKY_PLUGIN_SETTINGS_DIR = str(Path.home() / ".config" / "decksoundpad")
        DECKY_PLUGIN_RUNTIME_DIR = str(Path.home() / ".local" / "state" / "decksoundpad")
        DECKY_PLUGIN_LOG_DIR = str(
            Path.home() / ".local" / "state" / "decksoundpad" / "logs"
        )
        logger = logging.getLogger("decksoundpad.decky")

        @staticmethod
        async def emit(*_args: Any) -> None:
            return None

    decky = _DeckyFallback()  # type: ignore[assignment]


BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from decksoundpad import __version__
from decksoundpad.app import DeckSoundpadApp, start_healthcheck_loop
from decksoundpad.config import Settings, load_config
from decksoundpad.logging_setup import setup_logging
from decksoundpad.models import AudioStatus, LibraryStatus, PlayerStatus, Status
from decksoundpad.paths import AppPaths, ensure_app_dirs, resolve_paths
from decksoundpad.process import decky_runtime_env


EV_KEY = 0x01
BTN_TL2 = 0x138
BTN_TR2 = 0x139
BTN_TRIGGER_HAPPY1 = 0x2C0
BTN_TRIGGER_HAPPY40 = 0x2E7
BTN_GRIPL = 0x224
BTN_GRIPR = 0x225
BTN_GRIPL2 = 0x226
BTN_GRIPR2 = 0x227
INPUT_EVENT_STRUCT = struct.Struct("llHHI")
INPUT_EVENT_SIZE = INPUT_EVENT_STRUCT.size
L5_HOTKEY_DEBOUNCE_SECONDS = 0.45
L5_HOTKEY_CODES = {
    BTN_GRIPL2,
    # Diagnostic fallbacks for alternate Steam/Input stacks. These are logged
    # by name so we can tighten this after seeing real device output.
    BTN_GRIPL,
    BTN_TL2,
    BTN_TRIGGER_HAPPY1,
}
KEY_NAMES = {
    BTN_TL2: "BTN_TL2",
    BTN_TR2: "BTN_TR2",
    BTN_GRIPL: "BTN_GRIPL",
    BTN_GRIPR: "BTN_GRIPR",
    BTN_GRIPL2: "BTN_GRIPL2",
    BTN_GRIPR2: "BTN_GRIPR2",
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
STEAM_DECK_LBUTTON_L5 = 0x00008000
STEAM_DECK_LBUTTON_R5 = 0x00010000
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


class Plugin:
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
        self._healthcheck_stop: threading.Event | None = None
        self._hotkey_stop = threading.Event()
        self._hotkey_thread: threading.Thread | None = None
        self._hidraw_stop = threading.Event()
        self._hidraw_thread: threading.Thread | None = None
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
        self._external_overlay_input_grab_handles: list[tuple[str, str, Any]] = []
        self._external_overlay_input_grab_attempted = False
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
        self._stop_hotkey_monitor()
        self._stop_hidraw_monitor()
        self._stop_external_overlay_action_server()
        self._stop_external_overlay()
        stop_healthcheck = getattr(self, "_healthcheck_stop", None)
        if stop_healthcheck is not None:
            stop_healthcheck.set()
        app = getattr(self, "app", None)
        if app is not None:
            await asyncio.to_thread(app.player.stop_all)
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

    async def ensure_audio(self) -> dict[str, Any]:
        await self._call_backend(
            "audio_ensure",
            lambda app: app.ensure_audio(),
            fallback={},
        )
        return await self.get_status()

    async def repair_audio(self) -> dict[str, Any]:
        await self._call_backend(
            "audio_repair",
            lambda app: app.repair_audio(),
            fallback={},
        )
        return await self.get_status()

    async def get_settings(self) -> dict[str, Any]:
        return await self._call_backend(
            "settings",
            lambda app: app.settings_payload(),
            fallback=self.settings.to_dict(),
        )

    async def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
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
        return result

    def _create_backend(self) -> DeckSoundpadApp:
        return DeckSoundpadApp(self.paths, settings=self.settings, logger=self.logger)

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
            self._append_bridge_log("backend initialization: repair audio routing")
            repair_response = app.repair_audio()
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
        self._healthcheck_stop = start_healthcheck_loop(self._backend())

    def _start_hotkey_monitor(self) -> None:
        if not _input_hotkey_monitor_enabled():
            self._append_bridge_log("L5 OS hotkey monitor disabled: no root input access")
            return
        if self._hotkey_thread is not None and self._hotkey_thread.is_alive():
            return
        self._hotkey_stop.clear()
        self._hotkey_thread = threading.Thread(
            target=self._hotkey_monitor_worker,
            name="decksoundpad-l5-hotkey",
            daemon=True,
        )
        self._hotkey_thread.start()

    def _stop_hotkey_monitor(self) -> None:
        stop = getattr(self, "_hotkey_stop", None)
        if stop is not None:
            stop.set()
        thread = getattr(self, "_hotkey_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)

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
            thread.join(timeout=0.5)

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

    def _external_overlay_runtime_dir(self) -> Path:
        identity = self._external_overlay_target_identity()
        if identity is None:
            return self.paths.runtime_dir / "external-overlay"
        uid, _gid, _username, _home = identity
        user_runtime = Path(f"/run/user/{uid}")
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
        env.pop("WAYLAND_DISPLAY", None)
        return env

    def _external_overlay_preexec(self) -> Callable[[], None] | None:
        identity = self._external_overlay_target_identity()
        if identity is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
            return None

        uid, gid, username, _home = identity
        if uid == 0:
            return None

        def demote() -> None:
            os.setgid(gid)
            try:
                os.initgroups(username, gid)
            except OSError:
                pass
            os.setuid(uid)

        return demote

    def _prepare_external_overlay_runtime_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        identity = self._external_overlay_target_identity()
        if identity is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
            return
        uid, gid, _username, _home = identity
        try:
            os.chown(path, uid, gid)
            path.chmod(0o700)
        except OSError as exc:
            self._append_bridge_log(f"external overlay runtime dir ownership failed: {exc}")

    def _prepare_external_overlay_log_file(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        except OSError as exc:
            self._append_bridge_log(f"external overlay log file prepare failed: {exc}")
            return

        identity = self._external_overlay_target_identity()
        if identity is not None and hasattr(os, "geteuid") and os.geteuid() == 0:
            uid, gid, _username, _home = identity
            try:
                os.chown(path.parent, uid, gid)
                os.chown(path, uid, gid)
            except OSError as exc:
                self._append_bridge_log(f"external overlay log ownership failed: {exc}")
        try:
            path.parent.chmod(0o775)
            path.chmod(0o664)
        except OSError:
            pass

    def _start_external_overlay_action_server(self) -> None:
        thread = getattr(self, "_external_overlay_action_thread", None)
        if thread is not None and thread.is_alive():
            return
        self._external_overlay_action_stop.clear()
        thread = threading.Thread(
            target=self._external_overlay_action_server_worker,
            name="decksoundpad-overlay-actions",
            daemon=True,
        )
        self._external_overlay_action_thread = thread
        thread.start()

    def _stop_external_overlay_action_server(self) -> None:
        stop = getattr(self, "_external_overlay_action_stop", None)
        if stop is not None:
            stop.set()
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
            thread.join(timeout=0.5)

    def _external_overlay_action_server_worker(self) -> None:
        socket_path = self._external_overlay_action_socket_path()
        try:
            self._prepare_external_overlay_runtime_dir(socket_path.parent)
            socket_path.unlink(missing_ok=True)
        except OSError as exc:
            self._append_bridge_log(f"external overlay action socket prepare failed: {exc}")
            return

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(socket_path))
            self._prepare_external_overlay_socket_file(socket_path, mode=0o666)
            server.listen(8)
            server.settimeout(0.5)
            self._append_bridge_log(f"external overlay action socket listening path={socket_path}")
            while not self._external_overlay_action_stop.is_set():
                try:
                    client, _addr = server.accept()
                except socket.timeout:
                    continue
                with client:
                    payload = client.recv(64 * 1024)
                    if not payload:
                        continue
                    for line in payload.splitlines():
                        try:
                            command = json.loads(line.decode("utf-8"))
                        except json.JSONDecodeError as exc:
                            self._append_bridge_log(f"external overlay action invalid json: {exc}")
                            continue
                        self._handle_external_overlay_action(command)
        except OSError as exc:
            self._append_bridge_log(f"external overlay action socket failed: {exc}")
        finally:
            server.close()
            try:
                socket_path.unlink()
            except FileNotFoundError:
                pass

    def _prepare_external_overlay_socket_file(self, path: Path, *, mode: int) -> None:
        identity = self._external_overlay_target_identity()
        if identity is not None and hasattr(os, "geteuid") and os.geteuid() == 0:
            uid, gid, _username, _home = identity
            try:
                os.chown(path, uid, gid)
            except OSError as exc:
                self._append_bridge_log(f"external overlay socket ownership failed: {exc}")
        try:
            path.chmod(mode)
        except OSError as exc:
            self._append_bridge_log(f"external overlay socket chmod failed: {exc}")

    def _handle_external_overlay_action(self, command: dict[str, Any]) -> None:
        if not isinstance(command, dict):
            return
        command_type = command.get("type")
        if command_type == "input":
            action = clean_log_text(str(command.get("action", "")), 40)
            if action:
                self._append_bridge_log(f"external overlay touch action input={action}")
                self._external_overlay_input_sync(action)
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
                preexec_fn=self._external_overlay_preexec(),
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

    def _external_overlay_failure_response(self, exc: Exception) -> dict[str, Any]:
        message = clean_log_text(str(exc) or repr(exc) or type(exc).__name__, 500)
        if not message:
            message = type(exc).__name__
        tail = self._external_overlay_log_tail()
        error = message
        if tail and tail not in error:
            error = f"{error}; overlay log: {tail}"
        return {
            "ok": False,
            "visible": self._external_overlay_visible,
            "error": error,
            "log_tail": tail,
        }

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
            log_handle = log_file.open("a", encoding="utf-8")
            self._external_overlay_process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                env=env,
                start_new_session=True,
                preexec_fn=self._external_overlay_preexec(),
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
        self._release_external_overlay_input_grab()
        process = getattr(self, "_external_overlay_process", None)
        if process is None:
            return
        try:
            self._send_external_overlay_command({"type": "quit"}, start_process=False)
        except Exception:
            pass
        try:
            process.terminate()
        except OSError:
            pass

    def _grab_external_overlay_input_devices(self) -> None:
        if self._external_overlay_input_grab_handles or self._external_overlay_input_grab_attempted:
            return
        self._external_overlay_input_grab_attempted = True
        if fcntl is None:
            self._append_bridge_log("external overlay input grab unavailable: missing fcntl")
            return

        try:
            event_paths = sorted(Path("/dev/input").glob("event*"))
        except OSError as exc:
            self._append_bridge_log(f"external overlay input grab scan failed: {exc}")
            return

        grabbed: list[tuple[str, str, Any]] = []
        for path in event_paths:
            try:
                handle = path.open("rb", buffering=0)
            except OSError:
                continue
            name = input_device_name(handle)
            if not should_grab_overlay_input_device(name):
                try:
                    handle.close()
                except OSError:
                    pass
                continue
            try:
                fcntl.ioctl(handle.fileno(), EVIOCGRAB, 1)
            except OSError as exc:
                self._append_bridge_log(
                    f"external overlay input grab failed device={path} name={name!r}: {exc}"
                )
                try:
                    handle.close()
                except OSError:
                    pass
                continue
            grabbed.append((str(path), name, handle))

        self._external_overlay_input_grab_handles = grabbed
        if grabbed:
            devices = ",".join(f"{path}:{name or 'unknown'}" for path, name, _handle in grabbed)
            self._append_bridge_log(f"external overlay input grab enabled devices={devices}")
        else:
            self._append_bridge_log("external overlay input grab found no gamepad event devices")

    def _release_external_overlay_input_grab(self) -> None:
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

    def _sync_external_overlay_input_grab(self) -> None:
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
            except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError) as exc:
                last_error = exc
                if attempt == 3 and start_process:
                    self._ensure_external_overlay_process()
                time.sleep(0.08)
        tail = self._external_overlay_log_tail()
        detail = f"external overlay socket unavailable: {last_error}"
        if tail:
            detail = f"{detail}; log: {tail}"
        raise RuntimeError(detail)

    def _toggle_external_overlay_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
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

    def _external_overlay_input_sync(self, action: str) -> dict[str, Any]:
        safe_action = clean_log_text(str(action), 40)
        with self._external_overlay_lock:
            if not self._external_overlay_visible:
                return {"ok": True, "visible": False}

            if action == "hide":
                self._external_overlay_visible = False
            elif action == "next":
                self._move_external_overlay_selection(1)
            elif action == "prev":
                self._move_external_overlay_selection(-1)
            elif action == "right":
                self._move_external_overlay_selection(1)
            elif action == "left":
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

    def _play_previous_external_overlay_sound_sync(self) -> dict[str, Any]:
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
        }
        if self._external_overlay_visible:
            self._sync_external_overlay_input_grab()
        self._send_external_overlay_command(command)
        if not self._external_overlay_visible:
            self._sync_external_overlay_input_grab()

    def _hidraw_monitor_worker(self) -> None:
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
                                continue
                            pressed = buttons & ~previous
                            if pressed & STEAM_DECK_LBUTTON_L5:
                                self._append_bridge_log(
                                    "Steam Deck HID L5 press "
                                    f"device={device_path} buttons_l=0x{buttons_l:08x} "
                                    f"buttons_h=0x{buttons_h:08x}"
                                )
                                self._handle_l5_direct_hotkey("hidraw-input")
                                continue
                            if pressed & STEAM_DECK_LBUTTON_R5:
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

    def _handle_hidraw_overlay_buttons(self, pressed: int, device_path: str) -> None:
        for mask, action in STEAM_DECK_HID_ACTIONS:
            if not pressed & mask:
                continue
            now = time.monotonic()
            last_at = self._hidraw_action_last_at.get(action, 0.0)
            if now - last_at < HIDRAW_ACTION_DEBOUNCE_SECONDS:
                self._append_bridge_log(
                    "Steam Deck HID overlay input debounced "
                    f"device={device_path} action={action} mask=0x{mask:08x}"
                )
                return
            self._hidraw_action_last_at[action] = now
            self._append_bridge_log(
                "Steam Deck HID overlay input "
                f"device={device_path} action={action} mask=0x{mask:08x}"
            )
            try:
                response = self._external_overlay_input_sync(action)
                self._append_bridge_log(
                    "Steam Deck HID overlay input handled "
                    f"action={action} visible={bool(response.get('visible'))}"
                )
            except Exception as exc:
                self._record_bridge_exception(f"handle Steam Deck HID action {action}", exc)
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
            response = self._external_overlay_input_sync(direction)
            self._append_bridge_log(
                "Steam Deck HID overlay stick input handled "
                f"direction={direction} visible={bool(response.get('visible'))}"
            )
        except Exception as exc:
            self._record_bridge_exception(f"handle Steam Deck HID stick direction {direction}", exc)

    def _hotkey_monitor_worker(self) -> None:
        self._append_bridge_log("L5 OS hotkey monitor starting")
        last_emit = 0.0
        diagnostic_presses = 0
        seen_press_codes: set[tuple[str, int]] = set()
        while not self._hotkey_stop.is_set():
            handles = self._open_input_event_devices()
            if not handles:
                self._append_bridge_log("L5 OS hotkey monitor found no readable /dev/input/event* devices")
                self._hotkey_stop.wait(5.0)
                continue
            self._append_bridge_log(
                "L5 OS hotkey monitor opened devices="
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
                                self._append_bridge_log(f"L5 OS hotkey read failed: {exc}")
                                raise
                            if len(data) != INPUT_EVENT_SIZE:
                                break
                            _sec, _usec, event_type, code, value = INPUT_EVENT_STRUCT.unpack(data)
                            if event_type == EV_KEY and value == 1:
                                if diagnostic_presses < HOTKEY_DIAGNOSTIC_PRESS_LIMIT:
                                    key = (device_path, code)
                                    if key not in seen_press_codes:
                                        seen_press_codes.add(key)
                                        diagnostic_presses += 1
                                        self._append_bridge_log(
                                            "L5 OS hotkey observed key press "
                                            f"device={device_path} code={code} "
                                            f"hex=0x{code:x} name={KEY_NAMES.get(code, 'unknown')} "
                                            f"{self._backend_steam_overlay_log_fragment()}"
                                        )
                                is_candidate = code in L5_HOTKEY_CODES or (
                                    BTN_TRIGGER_HAPPY1 <= code <= BTN_TRIGGER_HAPPY40
                                )
                                if is_candidate:
                                    self._append_bridge_log(
                                        "L5 OS hotkey candidate press "
                                        f"device={device_path} code={code} "
                                        f"hex=0x{code:x} name={KEY_NAMES.get(code, 'unknown')} "
                                        f"{self._backend_steam_overlay_log_fragment()}"
                                    )
                                    now = time.monotonic()
                                    if now - last_emit >= L5_HOTKEY_DEBOUNCE_SECONDS:
                                        last_emit = now
                                        self._handle_l5_os_hotkey()
            except OSError:
                self._hotkey_stop.wait(1.0)
            finally:
                for _path, handle in handles:
                    try:
                        handle.close()
                    except OSError:
                        pass
        self._append_bridge_log("L5 OS hotkey monitor stopped")

    def _open_input_event_devices(self) -> list[tuple[str, Any]]:
        handles: list[tuple[str, Any]] = []
        input_dir = Path("/dev/input")
        try:
            event_paths = sorted(input_dir.glob("event*"))
        except OSError as exc:
            self._append_bridge_log(f"L5 OS hotkey device scan failed: {exc}")
            return []
        for path in event_paths:
            try:
                handle = path.open("rb", buffering=0)
                os.set_blocking(handle.fileno(), False)
            except OSError as exc:
                self._append_bridge_log(f"L5 OS hotkey cannot open {path}: {exc}")
                continue
            handles.append((str(path), handle))
        return handles

    def _handle_l5_os_hotkey(self) -> None:
        self._handle_l5_direct_hotkey("os-input")

    def _handle_l5_direct_hotkey(self, source: str) -> None:
        self._append_bridge_log(
            f"L5 shortcut detected source={source} {self._backend_steam_overlay_log_fragment()}"
        )
        try:
            response = self._toggle_external_overlay_sync({"source": source})
            self._append_bridge_log(
                "L5 direct hotkey handled by backend "
                f"source={source} "
                f"visible={bool(response.get('visible'))} sounds_count={response.get('sounds_count', 0)}"
            )
        except Exception as exc:
            self._record_bridge_exception(f"handle L5 direct hotkey source={source}", exc)

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
            response = self._play_previous_external_overlay_sound_sync()
            self._append_bridge_log(
                "R5 direct previous sound handled "
                f"source={source} visible={bool(response.get('visible'))} "
                f"page={response.get('page')} selected_index={response.get('selected_index')}"
            )
        except Exception as exc:
            self._record_bridge_exception(f"handle R5 direct previous sound source={source}", exc)

    def _fallback_status(self, last_error: str) -> dict[str, Any]:
        mic_passthrough_enabled = False
        try:
            mic_passthrough_enabled = bool(self.settings.mic_passthrough_enabled)
        except Exception:
            pass
        status = Status(
            backend_running=False,
            audio=AudioStatus(last_error=last_error, state="offline"),
            player=PlayerStatus(
                backend=None,
                pw_play_available=False,
                ffmpeg_available=False,
                mpv_available=False,
                active_playbacks=0,
            ),
            library=LibraryStatus(count=0, last_scan_at=None),
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
            paths.public_log_dir.mkdir(parents=True, exist_ok=True)
            with paths.public_bridge_log_file.open("a", encoding="utf-8") as handle:
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
        "audio_ensure",
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
            "active_playbacks": player.get("active_playbacks"),
        }
    if not summary:
        summary["keys"] = sorted(response)
    return summary


def parse_steam_deck_hid_report(data: bytes) -> dict[str, int] | None:
    for offset in (0, 1):
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

    if right_magnitude > left_magnitude:
        x = right_x
        y = right_y
    else:
        x = left_x
        y = left_y

    if abs(x) >= abs(y):
        return "right" if x > 0 else "left"
    return "down" if y > 0 else "up"


def eviocgname(length: int) -> int:
    # Linux _IOC(_IOC_READ, 'E', 0x06, length)
    return (2 << 30) | (length << 16) | (ord("E") << 8) | 0x06


def input_device_name(handle: Any) -> str:
    if fcntl is None:
        return ""
    buffer = bytearray(256)
    try:
        fcntl.ioctl(handle.fileno(), eviocgname(len(buffer)), buffer, True)
    except OSError:
        return ""
    raw = bytes(buffer).split(b"\x00", 1)[0]
    return raw.decode("utf-8", errors="replace")


def should_grab_overlay_input_device(name: str) -> bool:
    lowered = name.lower()
    if not lowered:
        return False
    if any(fragment in lowered for fragment in OVERLAY_INPUT_GRAB_NAME_EXCLUDES):
        return False
    return any(fragment in lowered for fragment in OVERLAY_INPUT_GRAB_NAME_HINTS)


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
