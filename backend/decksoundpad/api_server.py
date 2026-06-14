from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import queue
import socket
import struct
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .audio_player import PlaybackManager, select_backend
from .audio_router import AudioRouter
from .config import Settings, load_config, patch_settings, save_config
from .library import SoundLibrary
from .models import AudioStatus, LibraryStatus, PlayerStatus, Status, WebStatus
from .paths import AppPaths, ensure_app_dirs
from .process import command_exists, decky_runtime_env, run_capture
from .security import redact_token
from .simulation import SimulatedAudioRouter, SimulatedPlaybackManager, simulation_enabled


PUBLIC_ROUTES = {"/healthz"}
EVENT_KEEPALIVE_SECONDS = 15
PLAYBACK_ROUTE_READY_CACHE_SECONDS = 30.0
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WEBSOCKET_MAX_FRAME_BYTES = 1024 * 1024


class DeckSoundpadApp:
    def __init__(
        self,
        paths: AppPaths,
        *,
        settings: Settings | None = None,
        logger: logging.Logger | None = None,
    ):
        ensure_app_dirs(paths)
        self.paths = paths
        self.settings = settings or load_config(paths)
        self.logger = logger or logging.getLogger("decksoundpad")
        self.simulation = simulation_enabled()
        self.library = SoundLibrary(paths, self.settings)
        if self.simulation:
            self.logger.warning("DeckSoundpad simulation mode enabled")
            self.router = SimulatedAudioRouter(paths, self.settings)
            self.player = SimulatedPlaybackManager(self.settings)
        else:
            self.router = AudioRouter(paths, self.settings)
            self.player = PlaybackManager(
                self.settings,
                logger=self.logger.getChild("playback"),
            )
        self.logger.info("DeckSoundpad daemon app initialized version=%s", __version__)
        self.actual_port = self.settings.web_port
        self._events: list[queue.Queue[dict[str, Any]]] = []
        self._events_lock = threading.Lock()
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_lock = threading.Lock()
        self._audio_task_lock = threading.Lock()
        self._audio_task_running = False
        self._audio_task_name: str | None = None
        self._audio_task_started_at: str | None = None
        self._playback_route_lock = threading.Lock()
        self._playback_route_status: AudioStatus | None = None
        self._playback_route_checked_at = 0.0

    def status(self) -> dict[str, Any]:
        audio_status = self.router.healthcheck()
        self._remember_playback_route_status(audio_status)
        payload = self._status_payload(audio_status)
        self._store_status_cache(payload)
        return payload

    def quick_status(self) -> dict[str, Any]:
        with self._status_cache_lock:
            if self._status_cache is not None:
                return self._status_cache
        return self._status_payload(
            AudioStatus(last_error="Audio status pending", state="pending"),
            include_web_url=False,
        )

    def _status_payload(
        self,
        audio_status: AudioStatus,
        *,
        include_web_url: bool = True,
    ) -> dict[str, Any]:
        player_status = PlayerStatus(
            backend=self.best_backend_name(),
            pw_play_available=command_exists("pw-play"),
            ffmpeg_available=command_exists("ffmpeg"),
            mpv_available=command_exists("mpv"),
            active_playbacks=self.player.active_count(),
        )
        library_status = LibraryStatus(
            count=len(self.library.cached_items()),
            last_scan_at=self.library.last_scan_at,
        )
        web_status = WebStatus(
            url=self.web_url() if include_web_url else None,
            port=self.actual_port,
        )
        status_payload = Status(
            daemon_running=True,
            audio=audio_status,
            player=player_status,
            library=library_status,
            web=web_status,
        ).to_dict()
        status_payload["mic_passthrough_enabled"] = self.settings.mic_passthrough_enabled
        status_payload["version"] = __version__
        status_payload["playback_route"] = self._playback_route_payload()
        return status_payload

    def _store_status_cache(self, payload: dict[str, Any]) -> None:
        with self._status_cache_lock:
            self._status_cache = payload

    def capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "audio": self.router.probe().to_dict(),
            "player_backends": [
                {
                    "name": backend.name,
                    "available": backend.is_available(),
                }
                for backend in self.player.backends
            ],
            "allowed_extensions": self.settings.allowed_extensions,
        }

    def list_sounds(self) -> dict[str, Any]:
        sounds = self.library.cached_items()
        if not sounds:
            sounds = self.library.scan()
        return {"ok": True, "sounds": [sound.to_dict() for sound in sounds]}

    def refresh_library(self) -> dict[str, Any]:
        sounds = self.library.scan()
        payload = {"count": len(sounds)}
        self.broadcast("library_updated", payload)
        return {"ok": True, "sounds": [sound.to_dict() for sound in sounds]}

    def play_sound(self, payload: dict[str, Any]) -> dict[str, Any]:
        sound_id = str(payload.get("sound_id") or "")
        volume = payload.get("volume")
        cached_sounds = self.library.cached_items()
        self.logger.info(
            "playback api request sound_id=%s volume=%s cached_sounds=%s",
            sound_id,
            volume,
            len(cached_sounds),
        )
        sound = self.library.get_by_id(sound_id)
        if sound is None:
            self.logger.warning(
                "playback sound not found sound_id=%s cached_sounds=%s sample_sounds=%s",
                sound_id,
                len(cached_sounds),
                self._sound_debug_sample(cached_sounds),
            )
            return {"ok": False, "error": "sound not found"}
        sound_path = Path(sound.path)
        self.logger.info(
            "playback sound resolved sound_id=%s name=%s category=%s relative_path=%s path=%s exists=%s size_bytes=%s extension=%s",
            sound.id,
            sound.display_name,
            sound.category,
            sound.relative_path,
            sound_path,
            sound_path.exists(),
            file_size_for_log(sound_path),
            sound.extension,
        )
        try:
            route_status = self._ensure_playback_route()
            self.logger.info(
                "playback route ready sound_id=%s status=%s",
                sound.id,
                route_status.to_dict(),
            )
            playback_id = self.player.play(
                sound.id,
                sound_path,
                None if volume is None else float(volume),
            )
        except Exception as exc:
            self._forget_playback_route_status()
            message = str(exc)
            self.logger.warning("playback failed sound_id=%s error=%s", sound.id, message, exc_info=True)
            self.broadcast("error", {"message": message, "code": "playback_failed"})
            return {"ok": False, "error": message, "sound_id": sound.id}
        backend_name = self._playback_backend_name(playback_id)
        route_payload = self._playback_route_payload(backend_name)
        event_payload = {
            "playback_id": playback_id,
            "sound_id": sound.id,
            "backend": backend_name,
            "route": route_payload,
        }
        self.logger.info(
            "playback api success sound_id=%s playback_id=%s backend=%s route=%s",
            sound.id,
            playback_id,
            backend_name,
            route_payload,
        )
        self.broadcast("playback_started", event_payload)
        return {"ok": True, **event_payload}

    def _playback_backend_name(self, playback_id: str) -> str | None:
        getter = getattr(self.player, "playback_backend_name", None)
        if callable(getter):
            return getter(playback_id)
        playback = getattr(self.player, "playbacks", {}).get(playback_id)
        return getattr(playback, "backend_name", None) or (
            self.player.backends[0].name if self.player.backends else None
        )

    def _playback_route_payload(self, backend_name: str | None = None) -> dict[str, Any]:
        return {
            "backend": backend_name or self.best_backend_name(),
            "virtual_input": "decksoundpad_mic",
            "sink": "decksoundpad_sink",
            "mode": "stream_to_internal_sink",
        }

    def _ensure_playback_route(self) -> AudioStatus:
        cached = self._cached_ready_playback_route()
        if cached is not None:
            status, age_seconds = cached
            self.logger.info(
                "playback route using cached ready status age_seconds=%.3f status=%s",
                age_seconds,
                status.to_dict(),
            )
            return status

        status = self.router.healthcheck()
        self._remember_playback_route_status(status)
        self.logger.info("playback route precheck status=%s", status.to_dict())
        if self._audio_route_ready(
            status, include_mic_passthrough=self.settings.mic_passthrough_enabled
        ):
            return status

        self.logger.info("playback route ensure required status=%s", status.to_dict())
        status = self.router.ensure()
        self._remember_playback_route_status(status)
        self.logger.info("playback route ensure finished status=%s", status.to_dict())
        payload = self._status_payload(status)
        self._store_status_cache(payload)
        self.broadcast("status", payload)
        if self._audio_route_ready(
            status, include_mic_passthrough=self.settings.mic_passthrough_enabled
        ):
            return status

        if not status.pactl_available or not status.pipewire_available:
            message = "PipeWire/PulseAudio is unavailable; DeckSoundpad mic cannot be created"
        else:
            message = status.last_error or "DeckSoundpad mic route is unavailable; repair audio routing"
        raise RuntimeError(message)

    def _remember_playback_route_status(self, status: AudioStatus) -> None:
        with self._playback_route_lock:
            self._playback_route_status = status
            self._playback_route_checked_at = time.monotonic()

    def _forget_playback_route_status(self) -> None:
        with self._playback_route_lock:
            self._playback_route_status = None
            self._playback_route_checked_at = 0.0

    def _cached_ready_playback_route(self) -> tuple[AudioStatus, float] | None:
        with self._playback_route_lock:
            status = self._playback_route_status
            checked_at = self._playback_route_checked_at
        if status is None or not self._audio_route_ready(
            status, include_mic_passthrough=self.settings.mic_passthrough_enabled
        ):
            return None
        age_seconds = time.monotonic() - checked_at
        if age_seconds > PLAYBACK_ROUTE_READY_CACHE_SECONDS:
            return None
        return status, age_seconds

    @staticmethod
    def _audio_route_ready(
        status: AudioStatus, *, include_mic_passthrough: bool
    ) -> bool:
        if not status.sink_exists or not status.virtual_mic_exists:
            return False
        if not include_mic_passthrough:
            return True
        return status.selected_real_mic is None or status.loopback_exists

    @staticmethod
    def _sound_debug_sample(sounds: list[Any], limit: int = 8) -> list[dict[str, Any]]:
        return [
            {
                "id": sound.id,
                "relative_path": sound.relative_path,
                "display_name": sound.display_name,
            }
            for sound in sounds[:limit]
        ]

    def stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        playback_id = payload.get("playback_id")
        sound_id = payload.get("sound_id")
        if playback_id:
            self.player.stop_playback(str(playback_id))
        elif sound_id:
            self.player.stop_sound(str(sound_id))
        else:
            self.player.stop_all()
        self.broadcast("playback_finished", {"playback_id": playback_id, "sound_id": sound_id})
        return {"ok": True}

    def ensure_audio(self) -> dict[str, Any]:
        return self._start_audio_task("ensure", self.router.ensure).to_dict()

    def repair_audio(self) -> dict[str, Any]:
        return self._start_audio_task("repair", self.router.repair).to_dict()

    def _start_audio_task(self, name: str, operation: Any) -> AudioStatus:
        with self._audio_task_lock:
            if self._audio_task_running:
                state = "repairing" if self._audio_task_name == "repair" else "starting"
                return AudioStatus(
                    last_error="Audio initialization already running",
                    state=state,
                )
            self._audio_task_running = True
            self._audio_task_name = name
            self._audio_task_started_at = datetime.now(timezone.utc).isoformat()

        started_status = AudioStatus(
            last_error=f"Audio {name} started",
            state="repairing" if name == "repair" else "starting",
        )
        self._store_status_cache(self._status_payload(started_status))
        self.broadcast("status", self.quick_status())

        def run() -> None:
            try:
                self.logger.info("audio %s started", name)
                status = self._final_audio_status(operation())
                self.logger.info("audio %s finished status=%s", name, status.to_dict())
            except Exception as exc:
                self.logger.exception("audio %s failed", name)
                status = AudioStatus(last_error=f"Audio {name} failed: {exc}", state="error")
            finally:
                self._remember_playback_route_status(status)
                payload = self._status_payload(status)
                self._store_status_cache(payload)
                self.broadcast("status", payload)
                with self._audio_task_lock:
                    self._audio_task_running = False
                    self._audio_task_name = None
                    self._audio_task_started_at = None

        threading.Thread(target=run, name=f"decksoundpad-audio-{name}", daemon=True).start()
        return started_status

    def _final_audio_status(self, status: AudioStatus) -> AudioStatus:
        if status.state != "unknown":
            return status
        if status.last_error:
            return replace(status, state="error")
        if self._audio_route_ready(
            status, include_mic_passthrough=self.settings.mic_passthrough_enabled
        ):
            return replace(status, state="ready")
        if not status.pactl_available or not status.pipewire_available:
            return replace(status, state="unavailable")
        return replace(status, state="needs_repair")

    def _audio_task_snapshot(self) -> dict[str, Any]:
        with self._audio_task_lock:
            state = (
                "repairing"
                if self._audio_task_name == "repair"
                else "starting"
                if self._audio_task_running
                else "idle"
            )
            return {
                "running": self._audio_task_running,
                "name": self._audio_task_name,
                "started_at": self._audio_task_started_at,
                "state": state,
            }

    def settings_payload(self) -> dict[str, Any]:
        return self.settings.to_dict()

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        previous_mic_passthrough = self.settings.mic_passthrough_enabled
        self.settings = patch_settings(self.settings, patch)
        save_config(self.paths, self.settings)
        self.library = SoundLibrary(self.paths, self.settings)
        if self.simulation:
            self.router = SimulatedAudioRouter(self.paths, self.settings)
            self.player = SimulatedPlaybackManager(self.settings)
            status = self.router.healthcheck()
        else:
            self.router = AudioRouter(self.paths, self.settings)
            self.player.settings = self.settings
            if self.settings.mic_passthrough_enabled != previous_mic_passthrough:
                status = self.router.ensure()
            else:
                status = self.router.healthcheck()
        self._remember_playback_route_status(status)
        payload = self._status_payload(status)
        self._store_status_cache(payload)
        self.broadcast("status", payload)
        return self.settings_payload()

    def web_access(self) -> dict[str, Any]:
        url = self.web_url()
        return {
            "url": url,
            "port": self.actual_port,
        }

    def diagnostics(self) -> dict[str, Any]:
        def capture(args: list[str]) -> dict[str, Any]:
            if not command_exists(args[0]):
                return {"available": False, "stdout": "", "stderr": "command not found"}
            result = run_capture(args, timeout=5.0, env=decky_runtime_env())
            return {
                "available": True,
                "returncode": result.returncode,
                "stdout": redact_token(result.stdout),
                "stderr": redact_token(result.stderr),
            }

        return {
            "version": __version__,
            "simulation": self.simulation,
            "paths": {
                "plugin_dir": str(self.paths.plugin_dir),
                "settings_dir": str(self.paths.settings_dir),
                "runtime_dir": str(self.paths.runtime_dir),
                "log_dir": str(self.paths.log_dir),
                "public_log_dir": str(self.paths.public_log_dir),
                "user_home": str(self.paths.user_home),
            },
            "log_files": {
                "daemon": str(self.paths.daemon_log_file),
                "public_daemon": str(self.paths.public_daemon_log_file),
                "public_daemon_stdio": str(self.paths.public_daemon_stdio_log_file),
                "public_bridge": str(self.paths.public_bridge_log_file),
            },
            "commands": {
                "pactl": command_exists("pactl"),
                "paplay": command_exists("paplay"),
                "pacat": command_exists("pacat"),
                "pw-play": command_exists("pw-play"),
                "ffmpeg": command_exists("ffmpeg"),
                "mpv": command_exists("mpv"),
            },
            "web": {
                "url": self.web_url(),
                "actual_port": self.actual_port,
                "configured_port": self.settings.web_port,
                "auto_port": self.settings.auto_port,
            },
            "audio_task": self._audio_task_snapshot(),
            "pactl_info": capture(["pactl", "info"]),
            "default_source": capture(["pactl", "get-default-source"]),
            "sinks": capture(["pactl", "list", "sinks", "short"]),
            "sources": capture(["pactl", "list", "sources", "short"]),
            "sink_inputs": capture(["pactl", "list", "sink-inputs", "short"]),
            "source_outputs": capture(["pactl", "list", "source-outputs", "short"]),
            "modules": {
                **capture(["pactl", "list", "modules", "short"]),
                "filtered_hint": "filter for decksoundpad_sink, decksoundpad_mic, or DeckSoundpad",
            },
            "settings": self._redacted_settings(),
            "logs": self.tail_logs(200),
        }

    def tail_logs(self, lines: int) -> dict[str, Any]:
        max_lines = max(1, min(lines, 1000))
        log_files = [
            ("Private daemon", self.paths.daemon_log_file),
            ("Public daemon", self.paths.public_daemon_log_file),
            ("Public daemon stdio", self.paths.public_daemon_stdio_log_file),
            ("Public bridge", self.paths.public_bridge_log_file),
        ]
        output: list[str] = []
        seen: set[str] = set()
        for label, path in log_files:
            path_key = str(path)
            if path_key in seen:
                continue
            seen.add(path_key)
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                output.extend([f"== {label}: {path} ==", f"read failed: {exc}", ""])
                continue
            output.append(f"== {label}: {path} ==")
            output.extend(redact_token(line) for line in content[-max_lines:])
            output.append("")
        return {
            "ok": True,
            "public_log_dir": str(self.paths.public_log_dir),
            "lines": output,
        }

    def best_backend_name(self) -> str | None:
        probes = [Path(f"probe{extension}") for extension in self.settings.allowed_extensions]
        for probe in probes:
            backend = select_backend(probe, self.player.backends)
            if backend is not None:
                return backend.name
        return None

    def web_url(self) -> str:
        host = primary_lan_ip()
        return f"http://{host}:{self.actual_port}/"

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        with self._events_lock:
            self._events.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._events_lock:
            if subscriber in self._events:
                self._events.remove(subscriber)

    def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload}
        with self._events_lock:
            subscribers = list(self._events)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue

    def _redacted_settings(self) -> dict[str, Any]:
        return self.settings.to_dict()


class DeckSoundpadHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], app: DeckSoundpadApp):
        super().__init__(server_address, DeckSoundpadHandler)
        self.app = app


class DeckSoundpadHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DeckSoundpad/0.1"

    @property
    def app(self) -> DeckSoundpadApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        try:
            self._handle_get(include_body=True)
        except Exception as exc:
            self.app.logger.exception("GET failed path=%s", self.path)
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_HEAD(self) -> None:
        try:
            self._handle_get(include_body=False)
        except Exception as exc:
            self.app.logger.exception("HEAD failed path=%s", self.path)
            self._json(
                {"ok": False, "error": str(exc)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
                include_body=False,
            )

    def do_POST(self) -> None:
        try:
            self._handle_mutation("POST")
        except Exception as exc:
            self.app.logger.exception("POST failed path=%s", self.path)
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PATCH(self) -> None:
        try:
            self._handle_mutation("PATCH")
        except Exception as exc:
            self.app.logger.exception("PATCH failed path=%s", self.path)
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, fmt: str, *args: Any) -> None:
        self.app.logger.info("http %s", redact_token(fmt % args))

    def _handle_get(self, *, include_body: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v1/ws":
            if include_body:
                self._websocket(parsed.query)
            else:
                self._json({"ok": True}, include_body=False)
            return
        if path == "/healthz":
            self._text("ok\n", include_body=include_body)
            return
        if path.startswith("/api/v1/") and not self._authorized(parsed.query):
            self._json(
                {"ok": False, "error": "unauthorized"},
                HTTPStatus.UNAUTHORIZED,
                include_body=include_body,
            )
            return

        if path == "/api/v1/status":
            self._json(self.app.status(), include_body=include_body)
        elif path == "/api/v1/status/quick":
            self._json(self.app.quick_status(), include_body=include_body)
        elif path == "/api/v1/capabilities":
            self._json(self.app.capabilities(), include_body=include_body)
        elif path == "/api/v1/sounds":
            self._json(self.app.list_sounds(), include_body=include_body)
        elif path == "/api/v1/settings":
            self._json(self.app.settings_payload(), include_body=include_body)
        elif path == "/api/v1/web-access":
            self._json(self.app.web_access(), include_body=include_body)
        elif path == "/api/v1/logs/tail":
            lines = self._query_int(parsed.query, "lines", 200)
            self._json(self.app.tail_logs(lines), include_body=include_body)
        elif path == "/api/v1/diagnostics":
            self._json(
                {"ok": True, "diagnostics": self.app.diagnostics()},
                include_body=include_body,
            )
        elif path == "/api/v1/events":
            if include_body:
                self._events()
            else:
                self._json({"ok": True}, include_body=False)
        else:
            self._static(path, include_body=include_body)

    def _handle_mutation(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/v1/") and not self._authorized(parsed.query):
            self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        payload = self._body_json()
        result = self._dispatch_http_mutation(method, path, payload)
        if result is not None:
            self._json(result)
        else:
            self._json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

    def _dispatch_http_mutation(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if method == "POST" and path == "/api/v1/sounds/refresh":
            return self.app.refresh_library()
        if method == "POST" and path == "/api/v1/play":
            return self.app.play_sound(payload)
        if method == "POST" and path == "/api/v1/stop":
            return self.app.stop(payload)
        if method == "POST" and path == "/api/v1/audio/ensure":
            return self.app.ensure_audio()
        if method == "POST" and path == "/api/v1/audio/repair":
            return self.app.repair_audio()
        if method == "PATCH" and path == "/api/v1/settings":
            return self.app.update_settings(payload)
        return None

    def _dispatch_ws_action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "status":
            return self.app.status()
        if action == "status_quick":
            return self.app.quick_status()
        if action == "sounds":
            return self.app.list_sounds()
        if action == "sounds_refresh":
            return self.app.refresh_library()
        if action == "play":
            return self.app.play_sound(payload)
        if action == "stop":
            return self.app.stop(payload)
        if action == "audio_ensure":
            return self.app.ensure_audio()
        if action == "audio_repair":
            return self.app.repair_audio()
        if action == "logs_tail":
            return self.app.tail_logs(int(payload.get("lines", 200)))
        if action == "settings":
            return self.app.settings_payload()
        if action == "settings_update":
            return self.app.update_settings(payload)
        raise ValueError(f"unknown websocket action: {action}")

    def _authorized(self, query: str) -> bool:
        _ = query
        return True

    def _body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        *,
        include_body: bool = True,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(encoded)

    def _text(
        self,
        value: str,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        include_body: bool = True,
    ) -> None:
        encoded = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if include_body:
            self.wfile.write(encoded)

    def _events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        subscriber = self.app.subscribe()
        try:
            self._write_event({"type": "status", "payload": self.app.status()})
            while True:
                try:
                    event = subscriber.get(timeout=EVENT_KEEPALIVE_SECONDS)
                    self._write_event(event)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.app.unsubscribe(subscriber)

    def _write_event(self, event: dict[str, Any]) -> None:
        encoded = json.dumps(event, ensure_ascii=False)
        self.wfile.write(f"data: {encoded}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _websocket(self, query: str) -> None:
        if not self._authorized(query):
            self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        if self.headers.get("Upgrade", "").lower() != "websocket" or not key:
            self._json({"ok": False, "error": "websocket upgrade required"}, HTTPStatus.BAD_REQUEST)
            return

        accept_digest = hashlib.sha1(f"{key}{WEBSOCKET_GUID}".encode("ascii")).digest()
        accept = base64.b64encode(accept_digest).decode("ascii")
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True

        send_lock = threading.Lock()
        subscriber = self.app.subscribe()
        stop_event = threading.Event()

        def send(payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            frame = self._websocket_frame(encoded)
            with send_lock:
                self.wfile.write(frame)
                self.wfile.flush()

        def forward_events() -> None:
            while not stop_event.is_set():
                try:
                    event = subscriber.get(timeout=EVENT_KEEPALIVE_SECONDS)
                except queue.Empty:
                    try:
                        send({"type": "ping", "ts": time.time()})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        stop_event.set()
                    continue
                try:
                    send({"type": "event", "event": event})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    stop_event.set()

        thread = threading.Thread(target=forward_events, name="decksoundpad-ws-events", daemon=True)
        thread.start()
        try:
            send({"type": "event", "event": {"type": "status", "payload": self.app.status()}})
            while not stop_event.is_set():
                frame = self._read_websocket_frame()
                if frame is None:
                    break
                opcode, data = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self.wfile.write(self._websocket_frame(data, opcode=0xA))
                    self.wfile.flush()
                    continue
                if opcode != 0x1:
                    continue
                message: dict[str, Any] | None = None
                try:
                    message = json.loads(data.decode("utf-8"))
                    if not isinstance(message, dict):
                        raise ValueError("message must be a JSON object")
                    request_id = message.get("id")
                    action = str(message.get("action") or "")
                    payload = message.get("payload") or {}
                    if not isinstance(payload, dict):
                        raise ValueError("payload must be a JSON object")
                    result = self._dispatch_ws_action(action, payload)
                    send({"type": "response", "id": request_id, "ok": True, "result": result})
                except Exception as exc:
                    request_id = message.get("id") if isinstance(message, dict) else None
                    send({"type": "response", "id": request_id, "ok": False, "error": str(exc)})
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            stop_event.set()
            self.app.unsubscribe(subscriber)

    def _read_websocket_frame(self) -> tuple[int, bytes] | None:
        header = self.rfile.read(2)
        if len(header) < 2:
            return None
        first, second = header
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.rfile.read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.rfile.read(8))[0]
        if length > WEBSOCKET_MAX_FRAME_BYTES:
            raise ValueError("websocket frame too large")
        mask = self.rfile.read(4) if masked else b""
        data = self.rfile.read(length)
        if masked:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        return opcode, data

    @staticmethod
    def _websocket_frame(payload: bytes, opcode: int = 0x1) -> bytes:
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, length)
        elif length <= 0xFFFF:
            header = struct.pack("!BBH", first, 126, length)
        else:
            header = struct.pack("!BBQ", first, 127, length)
        return header + payload

    def _static(self, path: str, *, include_body: bool = True) -> None:
        root = self._web_root()
        requested = "index.html" if path in {"", "/"} else unquote(path.lstrip("/"))
        file_path = (root / requested).resolve()
        root_resolved = root.resolve()
        try:
            file_path.relative_to(root_resolved)
        except ValueError:
            self._json(
                {"ok": False, "error": "not found"},
                HTTPStatus.NOT_FOUND,
                include_body=include_body,
            )
            return
        if not file_path.exists() or not file_path.is_file():
            self._json(
                {"ok": False, "error": "not found"},
                HTTPStatus.NOT_FOUND,
                include_body=include_body,
            )
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def _web_root(self) -> Path:
        dist = self.app.paths.plugin_dir / "web" / "dist"
        if dist.exists():
            return dist
        return self.app.paths.plugin_dir / "web"

    @staticmethod
    def _query_int(query: str, key: str, default: int) -> int:
        value = parse_qs(query).get(key, [None])[0]
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default


def create_server(app: DeckSoundpadApp, host: str | None = None, port: int | None = None) -> DeckSoundpadHTTPServer:
    bind_host = host or app.settings.web_host
    first_port = port or app.settings.web_port
    candidate_ports = [first_port]
    if app.settings.auto_port:
        candidate_ports.extend(
            next_port
            for next_port in range(8787, 8798)
            if next_port != first_port
        )
    last_error: OSError | None = None
    for candidate in candidate_ports:
        try:
            server = DeckSoundpadHTTPServer((bind_host, candidate), app)
            app.actual_port = int(server.server_address[1])
            return server
        except OSError as exc:
            last_error = exc
            continue
    raise OSError(f"no available DeckSoundpad web port: {last_error}")


def write_session(paths: AppPaths, server: DeckSoundpadHTTPServer) -> None:
    payload = {
        "pid": os.getpid(),
        "host": "127.0.0.1",
        "bind_host": server.server_address[0],
        "port": server.server_address[1],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
    }
    ensure_app_dirs(paths)
    with paths.session_file.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def primary_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def file_size_for_log(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def start_healthcheck_loop(app: DeckSoundpadApp, interval_seconds: float = 8.0) -> threading.Event:
    stop_event = threading.Event()

    def run() -> None:
        while not stop_event.wait(interval_seconds):
            status = app.router.healthcheck()
            if (
                app.settings.auto_repair_on_resume
                and status.pactl_available
                and status.pipewire_available
                and (
                    not status.sink_exists
                    or not status.virtual_mic_exists
                    or (
                        app.settings.mic_passthrough_enabled
                        and status.selected_real_mic
                        and not status.loopback_exists
                    )
                )
            ):
                app.logger.info("auto repair triggered by healthcheck")
                status = app.router.repair()
            payload = app._status_payload(status)
            app._store_status_cache(payload)
            app.broadcast("status", payload)

    thread = threading.Thread(target=run, name="decksoundpad-healthcheck", daemon=True)
    thread.start()
    return stop_event
