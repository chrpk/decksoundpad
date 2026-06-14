from __future__ import annotations

import asyncio
import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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

from decksoundpad.config import Settings, load_config, patch_settings, save_config
from decksoundpad import __version__
from decksoundpad.logging_setup import setup_logging
from decksoundpad.models import AudioStatus, LibraryStatus, PlayerStatus, Status, WebStatus
from decksoundpad.paths import AppPaths, ensure_app_dirs, resolve_paths


class Plugin:
    async def _main(self) -> None:
        self.paths = resolve_paths(
            env=os.environ,
            plugin_dir=Path(getattr(decky, "DECKY_PLUGIN_DIR", Path(__file__).parent)),
        )
        ensure_app_dirs(self.paths)
        self.settings: Settings = load_config(self.paths)
        self.logger = setup_logging(self.paths)
        self.daemon_process: subprocess.Popen[bytes] | None = None
        self.daemon_log_handle = None
        self._daemon_lock = threading.Lock()
        self._daemon_start_thread: threading.Thread | None = None
        self._bridge_errors: list[str] = []
        self._last_daemon_start_attempt = 0.0
        self.logger.info("DeckSoundpad Decky bridge loaded")
        self._append_bridge_log(
            f"DeckSoundpad Decky bridge loaded version={__version__} "
            f"public_log_dir={self.paths.public_log_dir}"
        )
        self._request_daemon_start_background()

    async def _unload(self) -> None:
        if getattr(self, "settings", None) and self.settings.stop_daemon_on_plugin_unload:
            await asyncio.to_thread(self._stop_daemon)
        if self.daemon_log_handle is not None:
            self.daemon_log_handle.close()
        self.logger.info("DeckSoundpad Decky bridge unloaded")
        self._append_bridge_log("DeckSoundpad Decky bridge unloaded")

    async def get_status(self) -> dict[str, Any]:
        try:
            if not self._daemon_healthy(timeout=0.15):
                return self._offline_status()
            if not self._daemon_compatible(timeout=0.35):
                self._request_daemon_start_background()
                return self._fallback_status("daemon version mismatch; restarting in background")
            return self._request("GET", "/api/v1/status/quick", timeout=0.6)
        except Exception as exc:
            self._record_bridge_exception("get_status", exc)
            return self._fallback_status(f"bridge get_status failed: {exc}")

    async def start_daemon(self) -> dict[str, Any]:
        try:
            self._request_daemon_start_background()
            return self._offline_status(force_starting=True)
        except Exception as exc:
            self._record_bridge_exception("start_daemon", exc)
            return self._fallback_status(f"bridge start_daemon failed: {exc}")

    async def list_sounds(self) -> dict[str, Any]:
        return await self._proxy(
            "GET",
            "/api/v1/sounds",
            fallback={"ok": False, "sounds": [], "error": "daemon unavailable"},
        )

    async def play_sound(
        self, sound_id: str, volume: float | None = None
    ) -> dict[str, Any]:
        self._append_bridge_log(
            f"play_sound called sound_id={sound_id} volume={volume}"
        )
        return await self._proxy(
            "POST",
            "/api/v1/play",
            {"sound_id": sound_id, "volume": volume},
            fallback={"ok": False, "error": "daemon unavailable"},
            timeout=6.0,
        )

    async def stop_all(self) -> dict[str, Any]:
        return await self._proxy(
            "POST",
            "/api/v1/stop",
            {"playback_id": None, "sound_id": None},
            fallback={"ok": False, "error": "daemon unavailable"},
            timeout=2.0,
        )

    async def refresh_library(self) -> dict[str, Any]:
        return await self._proxy(
            "POST",
            "/api/v1/sounds/refresh",
            fallback={"ok": False, "error": "daemon unavailable", "sounds": []},
            timeout=5.0,
        )

    async def ensure_audio(self) -> dict[str, Any]:
        await self._proxy(
            "POST",
            "/api/v1/audio/ensure",
            fallback={},
            timeout=1.0,
            start_daemon=True,
        )
        return await self.get_status()

    async def repair_audio(self) -> dict[str, Any]:
        await self._proxy(
            "POST",
            "/api/v1/audio/repair",
            fallback={},
            timeout=1.0,
            start_daemon=True,
        )
        return await self.get_status()

    async def get_web_access(self) -> dict[str, Any]:
        return await self._proxy(
            "GET",
            "/api/v1/web-access",
            fallback={"url": None, "error": "daemon unavailable"},
            timeout=0.8,
            start_daemon=False,
        )

    async def get_settings(self) -> dict[str, Any]:
        return await self._proxy("GET", "/api/v1/settings", fallback=self.settings.to_dict())

    async def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not self._daemon_healthy(timeout=0.2):
            try:
                self.settings = patch_settings(self.settings, patch)
                save_config(self.paths, self.settings)
            except Exception as exc:
                self.logger.warning("local settings update failed error=%s", exc)
            return self.settings.to_dict()
        result = await self._proxy(
            "PATCH",
            "/api/v1/settings",
            patch,
            fallback=self.settings.to_dict(),
            timeout=3.0,
        )
        self.settings = load_config(self.paths)
        return result

    async def get_logs_tail(self, lines: int = 120) -> dict[str, Any]:
        safe_lines = max(1, min(int(lines), 500))
        try:
            response = await self._proxy(
                "GET",
                f"/api/v1/logs/tail?lines={safe_lines}",
                fallback={"ok": False, "lines": ["daemon unavailable"]},
            )
        except Exception as exc:
            self._record_bridge_exception("get_logs_tail", exc)
            response = {"ok": False, "lines": ["daemon unavailable"]}
        bridge_lines = self._bridge_log_lines()
        return {
            **response,
            "public_log_dir": self._public_log_dir(),
            "lines": bridge_lines + list(response.get("lines") or []),
        }

    async def get_diagnostics(self) -> dict[str, Any]:
        return await self._proxy(
            "GET",
            "/api/v1/diagnostics",
            fallback={"ok": False, "diagnostics": {"error": "daemon unavailable"}},
            timeout=10.0,
        )

    async def _proxy(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        fallback: dict[str, Any],
        timeout: float = 1.5,
        start_daemon: bool = False,
    ) -> dict[str, Any]:
        def call() -> dict[str, Any]:
            try:
                if not self._daemon_healthy(timeout=0.2):
                    if start_daemon:
                        self._request_daemon_start_background()
                        self._log_bridge_proxy(
                            method,
                            path,
                            "daemon not healthy; start requested and fallback returned",
                            payload,
                            fallback,
                        )
                        return fallback
                    self._log_bridge_proxy(
                        method,
                        path,
                        "daemon not healthy; fallback returned",
                        payload,
                        fallback,
                    )
                    return fallback
                if not self._daemon_compatible(timeout=0.35):
                    self._request_daemon_start_background()
                    self._log_bridge_proxy(
                        method,
                        path,
                        "daemon version mismatch; restart requested and fallback returned",
                        payload,
                        fallback,
                    )
                    return fallback
                response = self._request(method, path, payload, timeout=timeout)
                self._log_bridge_proxy(method, path, "daemon response", payload, response)
                return response
            except Exception as exc:
                self._record_bridge_exception(f"{method} {path}", exc)
                self._log_bridge_proxy(
                    method,
                    path,
                    f"exception fallback returned: {exc}",
                    payload,
                    fallback,
                )
                return fallback

        return await asyncio.to_thread(call)

    def _request_daemon_start_background(self) -> None:
        if not hasattr(self, "_daemon_lock"):
            self._daemon_lock = threading.Lock()
        with self._daemon_lock:
            thread = getattr(self, "_daemon_start_thread", None)
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._daemon_start_worker,
                name="decksoundpad-start-daemon",
                daemon=True,
            )
            self._daemon_start_thread = thread
            thread.start()

    def _daemon_start_worker(self) -> None:
        try:
            initialized = self._ensure_daemon_started()
            if initialized:
                self._initialize_daemon_from_scratch()
        except Exception as exc:
            self._record_bridge_exception("daemon_start_worker", exc)

    def _ensure_daemon_started(self) -> bool:
        if self._daemon_compatible(timeout=0.35):
            return False
        with self._daemon_lock:
            if self._daemon_compatible(timeout=0.35):
                return False
            session_pid = self._session_pid()
            if self._daemon_healthy(timeout=0.25):
                if self._session_process_is_decksoundpad(session_pid):
                    self.logger.info(
                        "stopping incompatible existing DeckSoundpad daemon "
                        "session_version=%s expected_version=%s",
                        self._session_version(),
                        __version__,
                    )
                    self._append_bridge_log(
                        "stopping incompatible daemon "
                        f"pid={session_pid} session_version={self._session_version()} "
                        f"expected_version={__version__}"
                    )
                    self._stop_daemon()
                else:
                    self.logger.warning(
                        "refusing to stop incompatible non-DeckSoundpad session pid=%s",
                        session_pid,
                    )
                    self._clear_session_if_pid(session_pid)
            elif self._process_alive(session_pid):
                if self._session_process_is_decksoundpad(session_pid):
                    self.logger.info("stopping stale existing DeckSoundpad daemon")
                    self._stop_daemon()
                else:
                    self.logger.warning(
                        "clearing stale DeckSoundpad session for non-DeckSoundpad pid=%s",
                        session_pid,
                    )
                    self._clear_session_if_pid(session_pid)
            elif session_pid is not None:
                self.logger.info("clearing stale DeckSoundpad session for dead pid=%s", session_pid)
                self._clear_session_if_pid(session_pid)
            now = time.monotonic()
            if now - self._last_daemon_start_attempt < 3.0:
                return False
            self._last_daemon_start_attempt = now
            self._start_daemon()
            return True

    def _initialize_daemon_from_scratch(self) -> None:
        if not self._wait_for_daemon_healthy(timeout=6.0):
            self._append_bridge_log("daemon post-start initialization skipped: health timeout")
            return
        if not self._daemon_compatible(timeout=1.0):
            self._append_bridge_log("daemon post-start initialization skipped: version mismatch after start")
            return
        self._append_bridge_log("daemon post-start initialization: repair audio routing")
        try:
            response = self._request("POST", "/api/v1/audio/repair", timeout=1.5)
            self._log_bridge_proxy("POST", "/api/v1/audio/repair", "post-start init response", None, response)
        except Exception as exc:
            self._record_bridge_exception("post-start audio repair", exc)
        self._append_bridge_log("daemon post-start initialization: refresh sound library")
        try:
            response = self._request("POST", "/api/v1/sounds/refresh", timeout=6.0)
            self._log_bridge_proxy("POST", "/api/v1/sounds/refresh", "post-start init response", None, response)
        except Exception as exc:
            self._record_bridge_exception("post-start library refresh", exc)

    def _start_daemon(self) -> None:
        self.logger.info("starting DeckSoundpad daemon")
        env = os.environ.copy()
        env.update(
            {
                "DECKY_PLUGIN_DIR": str(self.paths.plugin_dir),
                "DECKY_PLUGIN_SETTINGS_DIR": str(self.paths.settings_dir),
                "DECKY_PLUGIN_RUNTIME_DIR": str(self.paths.runtime_dir),
                "DECKY_PLUGIN_LOG_DIR": str(self.paths.log_dir),
                "DECKY_USER_HOME": str(self.paths.user_home),
                "PYTHONPATH": _prepend_pythonpath(str(BACKEND_DIR), env.get("PYTHONPATH")),
            }
        )
        if self.daemon_log_handle is not None:
            try:
                self.daemon_log_handle.close()
            except OSError:
                pass
        stdio_log_path = self._daemon_stdio_log_path()
        python_executable = _daemon_python_executable(env)
        self._append_bridge_log(
            "starting daemon "
            f"python={python_executable} sys_executable={sys.executable} "
            f"frozen={bool(getattr(sys, 'frozen', False))} stdio_log={stdio_log_path}"
        )
        try:
            self.daemon_log_handle = stdio_log_path.open("ab")
        except OSError as exc:
            self._append_bridge_log(
                f"daemon stdio log open failed path={stdio_log_path} error={exc}; falling back"
            )
            stdio_log_path = self.paths.daemon_log_file
            self.daemon_log_handle = stdio_log_path.open("ab")
        self.daemon_process = subprocess.Popen(
            [python_executable, "-m", "decksoundpad.daemon"],
            cwd=str(self.paths.plugin_dir),
            env=env,
            stdout=self.daemon_log_handle,
            stderr=self.daemon_log_handle,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._append_bridge_log(f"daemon process spawned pid={self.daemon_process.pid}")

    def _stop_daemon(self) -> None:
        pid = self._session_pid()
        if pid is None:
            return
        if not self._session_process_is_decksoundpad(pid):
            self.logger.warning("refusing to stop non-DeckSoundpad pid=%s", pid)
            self._clear_session_if_pid(pid)
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._clear_session_if_pid(pid)
            return
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not self._process_alive(pid):
                self._clear_session_if_pid(pid)
                return
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        finally:
            self._clear_session_if_pid(pid)

    def _daemon_healthy(self, timeout: float = 0.5) -> bool:
        try:
            request = Request(f"{self._base_url()}/healthz", method="GET")
            with urlopen(request, timeout=timeout) as response:
                return response.status == 200
        except Exception:
            return False

    def _wait_for_daemon_healthy(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._daemon_healthy(timeout=0.35):
                return True
            time.sleep(0.15)
        return False

    def _daemon_compatible(self, timeout: float = 0.5) -> bool:
        if not self._daemon_healthy(timeout=timeout):
            return False
        try:
            response = self._request("GET", "/api/v1/status/quick", timeout=timeout)
        except Exception:
            return False
        return response.get("version") == __version__

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 3.0,
    ) -> dict[str, Any]:
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url()}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read()
            if not raw:
                raise
        except URLError:
            raise
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("daemon returned a non-object JSON response")
        return value

    def _base_url(self) -> str:
        session = self._read_session()
        port = int(session.get("port") or self._settings_web_port())
        return f"http://127.0.0.1:{port}"

    def _read_session(self) -> dict[str, Any]:
        paths = getattr(self, "paths", None)
        if paths is None or not paths.session_file.exists():
            return {}
        try:
            with paths.session_file.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _session_pid(self) -> int | None:
        pid = self._read_session().get("pid")
        try:
            return int(pid) if pid is not None else None
        except (TypeError, ValueError):
            return None

    def _session_version(self) -> str | None:
        version = self._read_session().get("version")
        return version if isinstance(version, str) else None

    def _session_process_is_decksoundpad(self, pid: int | None) -> bool:
        if pid is None or not self._process_alive(pid):
            return False
        if self.daemon_process is not None and self.daemon_process.pid == pid:
            return self.daemon_process.poll() is None
        cmdline = self._process_cmdline(pid)
        return "decksoundpad.daemon" in " ".join(cmdline)

    @staticmethod
    def _process_cmdline(pid: int) -> list[str]:
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        try:
            raw = proc_cmdline.read_bytes()
            parts = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
            if parts:
                return parts
        except OSError:
            pass

        try:
            completed = subprocess.run(
                ["ps", "-p", str(pid), "-o", "args="],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if completed.returncode != 0:
            return []
        args = completed.stdout.strip()
        return [args] if args else []

    def _clear_session_if_pid(self, pid: int | None) -> None:
        session_pid = self._session_pid()
        if pid is None or session_pid != pid:
            return
        try:
            self.paths.session_file.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            self.logger.warning("failed to remove stale session file: %s", exc)

    @staticmethod
    def _process_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _offline_status(self, *, force_starting: bool = False) -> dict[str, Any]:
        try:
            daemon_starting = self._session_process_is_decksoundpad(self._session_pid())
        except Exception as exc:
            self._record_bridge_exception("_offline_status", exc)
            daemon_starting = False
        last_error = "daemon starting in background" if force_starting or daemon_starting else "daemon not running yet"
        return self._fallback_status(last_error)

    def _fallback_status(self, last_error: str) -> dict[str, Any]:
        status = Status(
            daemon_running=False,
            audio=AudioStatus(
                last_error=last_error,
                state="starting" if "starting" in last_error else "offline",
            ),
            player=PlayerStatus(
                backend=None,
                pw_play_available=False,
                ffmpeg_available=False,
                mpv_available=False,
                active_playbacks=0,
            ),
            library=LibraryStatus(count=0, last_scan_at=None),
            web=WebStatus(url=None, port=self._settings_web_port()),
        ).to_dict()
        status["version"] = __version__
        status["playback_route"] = {
            "backend": None,
            "virtual_input": "decksoundpad_mic",
            "sink": "decksoundpad_sink",
            "mode": "offline",
        }
        return status

    def _settings_web_port(self) -> int:
        settings = getattr(self, "settings", None)
        try:
            return int(getattr(settings, "web_port", 8787))
        except (TypeError, ValueError):
            return 8787

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

    def _bridge_log_lines(self) -> list[str]:
        errors = list(getattr(self, "_bridge_errors", []))
        return ["Bridge", *errors, ""] if errors else []

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

    def _log_bridge_proxy(
        self,
        method: str,
        path: str,
        message: str,
        payload: dict[str, Any] | None,
        response: dict[str, Any],
    ) -> None:
        if not bridge_path_is_interesting(path):
            return
        self._append_bridge_log(
            "proxy "
            f"{method} {path} {message} "
            f"payload={payload_summary_for_log(payload)} "
            f"response={response_summary_for_log(response)}"
        )

    def _daemon_stdio_log_path(self) -> Path:
        try:
            self.paths.public_log_dir.mkdir(parents=True, exist_ok=True)
            return self.paths.public_daemon_stdio_log_file
        except OSError as exc:
            self._append_bridge_log(f"public daemon stdio log unavailable: {exc}")
            return self.paths.daemon_log_file

    def _public_log_dir(self) -> str | None:
        paths = getattr(self, "paths", None)
        if paths is None:
            return None
        return str(paths.public_log_dir)


def _prepend_pythonpath(path: str, current: str | None) -> str:
    if not current:
        return path
    parts = current.split(os.pathsep)
    if path in parts:
        return current
    return os.pathsep.join([path, current])


def bridge_path_is_interesting(path: str) -> bool:
    interesting = (
        "/api/v1/play",
        "/api/v1/sounds",
        "/api/v1/sounds/refresh",
        "/api/v1/audio/ensure",
        "/api/v1/audio/repair",
        "/api/v1/settings",
    )
    return path in interesting or path.startswith("/api/v1/sounds")


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


def _daemon_python_executable(env: dict[str, str]) -> str:
    override = env.get("DECKSOUNDPAD_PYTHON")
    if override:
        return override
    if not getattr(sys, "frozen", False) and _looks_like_python(sys.executable):
        return sys.executable
    for command in ("python3", "python"):
        candidate = shutil.which(command)
        if candidate:
            return candidate
    return "/usr/bin/python3"


def _looks_like_python(executable: str) -> bool:
    name = Path(executable).name.lower()
    return name.startswith("python")
