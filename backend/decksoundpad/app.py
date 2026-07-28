from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import __version__
from .audio_player import PlaybackManager, select_backend
from .audio_router import AudioRouter
from .config import Settings, load_config, patch_settings, save_config
from .library import SoundLibrary
from .models import AudioStatus, LibraryStatus, PlayerStatus, Status
from .paths import AppPaths, ensure_app_dirs
from .simulation import (
    SimulatedAudioRouter,
    SimulatedPlaybackManager,
    simulation_enabled,
)

PLAYBACK_ROUTE_READY_CACHE_SECONDS = 30.0


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
        self._runtime_lock = threading.RLock()
        self.library, self.router, self.player = self._create_runtime_components(self.settings)
        self.logger.info("DeckSoundpad backend initialized version=%s", __version__)
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_lock = threading.Lock()
        self._audio_task_lock = threading.Lock()
        self._audio_task_running = False
        self._audio_task_name: str | None = None
        self._repair_task_running = False
        self._audio_generation = 0
        self._playback_route_lock = threading.Lock()
        self._playback_route_status: AudioStatus | None = None
        self._playback_route_checked_at = 0.0

    def _create_runtime_components(self, settings: Settings) -> tuple[Any, Any, Any]:
        library = SoundLibrary(self.paths, settings)
        if self.simulation:
            self.logger.warning("DeckSoundpad simulation mode enabled")
            router = SimulatedAudioRouter(self.paths, settings)
            player = SimulatedPlaybackManager(settings)
        else:
            router = AudioRouter(self.paths, settings)
            player = PlaybackManager(
                settings,
                logger=self.logger.getChild("playback"),
                paths=self.paths,
            )
        return library, router, player

    def status(self) -> dict[str, Any]:
        with self._runtime_lock:
            audio_status = self.router.healthcheck()
            self._remember_playback_route_status(audio_status)
            payload = self._status_payload(audio_status)
            self._store_status_cache(payload)
            return payload

    def quick_status(self) -> dict[str, Any]:
        with self._status_cache_lock:
            if self._status_cache is not None:
                return self._status_cache
        # Frontend status polling must stay responsive while the first full
        # PipeWire healthcheck is still running in the startup worker.
        return self._status_payload(AudioStatus(last_error="Audio status pending", state="pending"))

    def _status_payload(self, audio_status: AudioStatus) -> dict[str, Any]:
        player_status = PlayerStatus(
            backend=self.best_backend_name(),
        )
        library_status = LibraryStatus(
            count=len(self.library.cached_items()),
        )
        status_payload = Status(
            backend_running=True,
            audio=audio_status,
            player=player_status,
            library=library_status,
        ).to_dict()
        status_payload["mic_passthrough_enabled"] = self.settings.mic_passthrough_enabled
        status_payload["version"] = __version__
        status_payload["playback_route"] = self._playback_route_payload()
        return status_payload

    def _store_status_cache(self, payload: dict[str, Any]) -> None:
        with self._status_cache_lock:
            self._status_cache = payload

    def publish_status(self, status: AudioStatus) -> dict[str, Any]:
        with self._runtime_lock:
            payload = self._status_payload(status)
            self._store_status_cache(payload)
            return payload

    def publish_progress_status(self, status: AudioStatus) -> dict[str, Any]:
        with self._status_cache_lock:
            cached = dict(self._status_cache) if self._status_cache is not None else None
        if cached is None:
            payload = self._status_payload(status)
        else:
            payload = cached
            payload["audio"] = status.to_dict()
        self._store_status_cache(payload)
        return payload

    def list_sounds(self) -> dict[str, Any]:
        with self._runtime_lock:
            sounds = self.library.cached_items()
            if not sounds:
                sounds = self.library.scan()
            return {"ok": True, "sounds": [sound.to_dict() for sound in sounds]}

    def refresh_library(self) -> dict[str, Any]:
        with self._runtime_lock:
            sounds = self.library.scan()
            return {"ok": True, "sounds": [sound.to_dict() for sound in sounds]}

    def play_sound(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._runtime_lock:
            return self._play_sound(payload)

    def _play_sound(self, payload: dict[str, Any]) -> dict[str, Any]:
        sound_id = str(payload.get("sound_id") or "")
        volume = payload.get("volume")
        cached_sounds = self.library.cached_items()
        self.logger.info(
            "playback request sound_id=%s volume=%s cached_sounds=%s",
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
            "playback sound resolved sound_id=%s display_name=%s category=%s relative_path=%s path=%s exists=%s file_size=%s extension=%s",
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
            if self._can_play_hot(sound_path):
                route_status = self._cached_ready_playback_route_status()
                if route_status is None:
                    # Low-latency playback should not block on route repair;
                    # start the repair in the background and let playback try.
                    self._schedule_playback_route_check()
                    route_status = AudioStatus(last_error="Audio route check scheduled", state="pending")
            else:
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
            "playback success sound_id=%s playback_id=%s backend=%s route=%s",
            sound.id,
            playback_id,
            backend_name,
            route_payload,
        )
        return {"ok": True, **event_payload}

    def _can_play_hot(self, path: Path) -> bool:
        mixer = getattr(self.player, "low_latency", None)
        can_play = getattr(mixer, "can_play", None)
        return callable(can_play) and bool(can_play(path))

    def _cached_ready_playback_route_status(self) -> AudioStatus | None:
        cached = self._cached_ready_playback_route()
        if cached is None:
            return None
        status, _age_seconds = cached
        return status

    def _schedule_playback_route_check(self) -> None:
        with self._audio_task_lock:
            if self._audio_task_running or self._repair_task_running:
                return
            self._audio_task_running = True
            self._audio_task_name = "ensure"
            generation = self._audio_generation

        def run() -> None:
            status = AudioStatus(last_error="Audio route check interrupted", state="error")
            try:
                with self._runtime_lock:
                    status = self._final_audio_status(self.router.ensure())
            except Exception as exc:
                self.logger.exception("background playback route check failed")
                status = AudioStatus(last_error=f"Audio ensure failed: {exc}", state="error")
            finally:
                with self._audio_task_lock:
                    should_publish = (
                        generation == self._audio_generation and not self._repair_task_running
                    )
                    self._audio_task_running = False
                    self._audio_task_name = None
                if should_publish:
                    self._remember_playback_route_status(status)
                    self.publish_status(status)

        threading.Thread(target=run, name="decksoundpad-playback-route-check", daemon=True).start()

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
        self.publish_status(status)
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
        # PipeWire routes are cheap to recheck, but not on every sound trigger.
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

    def repair_audio(self) -> dict[str, Any]:
        return self._start_repair_task().to_dict()

    def _start_repair_task(self) -> AudioStatus:
        with self._audio_task_lock:
            if self._repair_task_running:
                return AudioStatus(
                    last_error="DeckSoundpad restart already running",
                    state="repairing",
                )
            self._repair_task_running = True
            self._audio_generation += 1

        started_status = AudioStatus(
            last_error="DeckSoundpad restart started",
            state="repairing",
        )
        self.publish_progress_status(started_status)

        def run() -> None:
            status = AudioStatus(last_error="DeckSoundpad restart interrupted", state="error")
            try:
                self.logger.info("DeckSoundpad runtime restart started")
                status = self._restart_runtime()
                self.logger.info("DeckSoundpad runtime restart finished status=%s", status.to_dict())
            except Exception as exc:
                self.logger.exception("DeckSoundpad runtime restart failed")
                status = AudioStatus(last_error=f"DeckSoundpad restart failed: {exc}", state="error")
            finally:
                self._remember_playback_route_status(status)
                try:
                    self.publish_status(status)
                except Exception:
                    self.logger.exception("failed to publish DeckSoundpad restart status")
                    try:
                        self.publish_progress_status(status)
                    except Exception:
                        self.logger.exception("failed to publish fallback restart status")
                finally:
                    with self._audio_task_lock:
                        self._repair_task_running = False

        threading.Thread(target=run, name="decksoundpad-runtime-restart", daemon=True).start()
        return started_status

    def _restart_runtime(self) -> AudioStatus:
        with self._runtime_lock:
            new_settings = load_config(self.paths)
            new_library, new_router, new_player = self._create_runtime_components(new_settings)
            old_player = self.player
            old_router = self.router
            self._close_runtime_player(old_player)
            self._teardown_runtime_router(old_router)
            self.settings = new_settings
            self.library = new_library
            self.router = new_router
            self.player = new_player
            self._forget_playback_route_status()
            try:
                return self._final_audio_status(self.router.ensure())
            finally:
                self.library.scan()

    def _close_runtime_player(self, player: Any) -> None:
        try:
            close = getattr(player, "close", None)
            if callable(close):
                close()
            else:
                player.stop_all()
        except Exception:
            self.logger.exception("failed to stop old playback runtime during restart")

    def _teardown_runtime_router(self, router: Any) -> None:
        teardown = getattr(router, "teardown", None)
        if not callable(teardown):
            return
        try:
            teardown()
        except Exception:
            self.logger.exception("failed to tear down old audio route during restart")

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

    def settings_payload(self) -> dict[str, Any]:
        with self._runtime_lock:
            return self.settings.to_dict()

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._runtime_lock:
            return self._update_settings(patch)

    def _update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
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
                # Changing mic passthrough adds or removes a loopback module, so
                # rebuild the audio route immediately instead of waiting for play.
                status = self.router.ensure()
            else:
                status = self.router.healthcheck()
        self._remember_playback_route_status(status)
        self.publish_status(status)
        return self.settings_payload()

    def run_healthcheck_cycle(self) -> AudioStatus | None:
        with self._runtime_lock:
            status = self.router.healthcheck()
            route_ready = self._audio_route_ready(
                status,
                include_mic_passthrough=self.settings.mic_passthrough_enabled,
            )
            if (
                self.settings.auto_repair_on_resume
                and status.pactl_available
                and status.pipewire_available
                and not route_ready
            ):
                self.logger.info("auto repair triggered by healthcheck")
                status = self.router.repair()
            with self._audio_task_lock:
                if self._repair_task_running:
                    return None
            self._remember_playback_route_status(status)
            self.publish_status(status)
            return status

    def best_backend_name(self) -> str | None:
        probes = [Path(f"probe{extension}") for extension in self.settings.allowed_extensions]
        for probe in probes:
            backend = select_backend(probe, self.player.backends)
            if backend is not None:
                return backend.name
        return None



def file_size_for_log(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def start_healthcheck_loop(app: DeckSoundpadApp, interval_seconds: float = 8.0) -> threading.Event:
    stop_event = threading.Event()

    def run() -> None:
        while not stop_event.wait(interval_seconds):
            app.run_healthcheck_cycle()

    thread = threading.Thread(target=run, name="decksoundpad-healthcheck", daemon=True)
    thread.start()
    return stop_event
