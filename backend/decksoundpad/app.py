from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import __version__
from .audio_player import PlaybackManager, select_backend
from .audio_router import AudioRouter
from .beep import write_beep_wav
from .config import Settings, load_config, patch_settings, save_config
from .library import SoundLibrary
from .models import AudioStatus, LibraryStatus, PlayerStatus, Status
from .paths import AppPaths, ensure_app_dirs, expand_user_path, user_owner
from .simulation import (
    SimulatedAudioRouter,
    SimulatedPlaybackManager,
    simulation_enabled,
)

PLAYBACK_ROUTE_READY_CACHE_SECONDS = 30.0
TEST_SOUND_ID = "test_beep"
# Settings that change which files a library scan returns.
LIBRARY_SETTING_KEYS = frozenset(
    {"library_dirs", "allowed_extensions", "allow_symlinks_outside_libraries"}
)


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
        self.library, self.router, self.player = self._create_runtime_components(
            self.settings
        )
        self.logger.info("DeckSoundpad backend initialized version=%s", __version__)
        self._status_cache: dict[str, Any] | None = None
        self._status_commit_lock = threading.RLock()
        self._audio_task_lock = threading.Lock()
        self._audio_task_running = False
        self._repair_task_running = False
        self._repair_done = threading.Event()
        self._repair_done.set()
        self._restart_sequence = 0
        self._active_restart_id: int | None = None
        self._completed_restart_id = 0
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
        with self._audio_task_lock:
            generation = self._audio_generation
        with self._runtime_lock:
            audio_status = self.router.healthcheck()
            self._remember_playback_route_status(
                audio_status,
                expected_generation=generation,
            )
        self.publish_status(audio_status, expected_generation=generation)
        return self.quick_status()

    def quick_status(self) -> dict[str, Any]:
        with self._status_commit_lock:
            payload = (
                dict(self._status_cache) if self._status_cache is not None else None
            )
            if payload is None:
                payload = self._pending_status_payload()
            return self._decorate_restart_status(payload)

    def _pending_status_payload(self) -> dict[str, Any]:
        payload = Status(
            backend_running=True,
            audio=AudioStatus(last_error="Audio status pending", state="pending"),
            player=PlayerStatus(backend=None),
            library=LibraryStatus(count=0, dirs=self._library_dir_paths()),
        ).to_dict()
        payload["version"] = __version__
        return payload

    def _library_dir_paths(self) -> list[str]:
        return [str(root) for root in self.library.roots()]

    def _decorate_restart_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._audio_task_lock:
            running = self._repair_task_running
            active_id = self._active_restart_id
            completed_id = self._completed_restart_id
        decorated = dict(payload)
        decorated["restart_running"] = running
        restart_id = active_id if active_id is not None else completed_id or None
        if restart_id is None:
            decorated.pop("restart_id", None)
        else:
            decorated["restart_id"] = restart_id
        decorated["restart_completed_id"] = completed_id
        if running:
            decorated["audio"] = AudioStatus(
                last_error="DeckSoundpad restart started",
                state="repairing",
            ).to_dict()
        return decorated

    def _status_payload(self, audio_status: AudioStatus) -> dict[str, Any]:
        player_status = PlayerStatus(
            backend=self.best_backend_name(),
        )
        library_status = LibraryStatus(
            count=len(self.library.cached_items()),
            dirs=self._library_dir_paths(),
        )
        status_payload = Status(
            backend_running=True,
            audio=audio_status,
            player=player_status,
            library=library_status,
        ).to_dict()
        status_payload["mic_passthrough_enabled"] = (
            self.settings.mic_passthrough_enabled
        )
        status_payload["version"] = __version__
        status_payload["playback_route"] = self._playback_route_payload()
        return status_payload

    def publish_status(
        self,
        status: AudioStatus,
        *,
        expected_generation: int | None = None,
        allow_during_restart: bool = False,
    ) -> dict[str, Any]:
        if expected_generation is None:
            with self._audio_task_lock:
                expected_generation = self._audio_generation
        with self._runtime_lock:
            payload = self._status_payload(status)
        with self._status_commit_lock:
            with self._audio_task_lock:
                can_commit = expected_generation == self._audio_generation and (
                    allow_during_restart or not self._repair_task_running
                )
            if can_commit:
                self._status_cache = payload
            return self._decorate_restart_status(payload)

    def publish_progress_status(
        self,
        status: AudioStatus,
        *,
        expected_generation: int | None = None,
    ) -> dict[str, Any]:
        with self._status_commit_lock:
            with self._audio_task_lock:
                generation_matches = (
                    expected_generation is None
                    or expected_generation == self._audio_generation
                )
            cached = (
                dict(self._status_cache) if self._status_cache is not None else None
            )
            payload = cached if cached is not None else self._pending_status_payload()
            if generation_matches:
                payload["audio"] = status.to_dict()
                self._status_cache = payload
            return self._decorate_restart_status(payload)

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

    def set_library_folder(self, folder: str) -> dict[str, Any]:
        with self._runtime_lock:
            try:
                path = expand_user_path(str(folder).strip(), self.paths.user_home)
                if not path.is_absolute():
                    raise ValueError(f"sound folder must be an absolute path: {folder}")
                settings = self._update_settings({"library_dirs": [str(path)]})
            except (OSError, ValueError) as exc:
                self.logger.warning("sound folder change rejected error=%s", exc)
                return {
                    "ok": False,
                    "error": str(exc),
                    "settings": self.settings_payload(),
                    "sounds": [],
                }
            sounds = self.library.cached_items()
            self.logger.info("sound folder changed sounds=%s", len(sounds))
            return {
                "ok": True,
                "settings": settings,
                "sounds": [sound.to_dict() for sound in sounds],
            }

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
        return self._play_path(sound.id, sound_path, volume)

    def playing_sound_ids(self, timeout: float = 0.05) -> frozenset[str] | None:
        """Return the sounds still playing, or None when playback is busy.

        The overlay polls this while it is open, so it must never wait behind a
        restart or a slow playback start.
        """

        if not self._runtime_lock.acquire(timeout=timeout):
            return None
        try:
            return frozenset(self.player.active_sound_ids())
        finally:
            self._runtime_lock.release()

    def stop_all_sounds(self) -> dict[str, Any]:
        with self._runtime_lock:
            self.player.stop_all()
        self.logger.info("playback stop all requested")
        return {"ok": True}

    def play_test_sound(self) -> dict[str, Any]:
        with self._runtime_lock:
            path = self.paths.test_beep_file
            try:
                write_beep_wav(path, owner=user_owner(self.paths))
            except OSError as exc:
                self.logger.warning(
                    "test beep write failed path=%s error=%s", path, exc
                )
                return {"ok": False, "error": f"could not create test beep: {exc}"}
            self.logger.info("playback request test beep path=%s", path)
            return self._play_path(TEST_SOUND_ID, path, None)

    def _play_path(
        self, sound_id: str, sound_path: Path, volume: Any
    ) -> dict[str, Any]:
        try:
            if self._can_play_hot(sound_path):
                route_status = self._cached_ready_playback_route_status()
                if route_status is None:
                    # Low-latency playback should not block on route repair;
                    # start the repair in the background and let playback try.
                    self._schedule_playback_route_check()
                    route_status = AudioStatus(
                        last_error="Audio route check scheduled", state="pending"
                    )
            else:
                route_status = self._ensure_playback_route()
            self.logger.info(
                "playback route ready sound_id=%s status=%s",
                sound_id,
                route_status.to_dict(),
            )
            playback_id = self.player.play(
                sound_id,
                sound_path,
                None if volume is None else float(volume),
            )
        except Exception as exc:
            self._forget_playback_route_status()
            message = str(exc)
            self.logger.warning(
                "playback failed sound_id=%s error=%s", sound_id, message, exc_info=True
            )
            return {"ok": False, "error": message, "sound_id": sound_id}
        backend_name = self._playback_backend_name(playback_id)
        route_payload = self._playback_route_payload(backend_name)
        event_payload = {
            "playback_id": playback_id,
            "sound_id": sound_id,
            "backend": backend_name,
            "route": route_payload,
        }
        self.logger.info(
            "playback success sound_id=%s playback_id=%s backend=%s route=%s",
            sound_id,
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
            generation = self._audio_generation

        def run() -> None:
            status = AudioStatus(
                last_error="Audio route check interrupted", state="error"
            )
            try:
                with self._runtime_lock:
                    status = self._final_audio_status(self.router.ensure())
            except Exception as exc:
                self.logger.exception("background playback route check failed")
                status = AudioStatus(
                    last_error=f"Audio ensure failed: {exc}", state="error"
                )
            finally:
                with self._audio_task_lock:
                    should_publish = (
                        generation == self._audio_generation
                        and not self._repair_task_running
                    )
                    self._audio_task_running = False
                if should_publish:
                    self._remember_playback_route_status(
                        status,
                        expected_generation=generation,
                    )
                    self.publish_status(status, expected_generation=generation)

        threading.Thread(
            target=run, name="decksoundpad-playback-route-check", daemon=True
        ).start()

    def _playback_backend_name(self, playback_id: str) -> str | None:
        getter = getattr(self.player, "playback_backend_name", None)
        if callable(getter):
            return getter(playback_id)
        playback = getattr(self.player, "playbacks", {}).get(playback_id)
        return getattr(playback, "backend_name", None) or (
            self.player.backends[0].name if self.player.backends else None
        )

    def _playback_route_payload(
        self, backend_name: str | None = None
    ) -> dict[str, Any]:
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
            message = (
                "PipeWire/PulseAudio is unavailable; DeckSoundpad mic cannot be created"
            )
        else:
            message = (
                status.last_error
                or "DeckSoundpad mic route is unavailable; repair audio routing"
            )
        raise RuntimeError(message)

    def _remember_playback_route_status(
        self,
        status: AudioStatus,
        *,
        expected_generation: int | None = None,
    ) -> bool:
        with self._status_commit_lock:
            if expected_generation is not None:
                with self._audio_task_lock:
                    if expected_generation != self._audio_generation:
                        return False
            with self._playback_route_lock:
                self._playback_route_status = status
                self._playback_route_checked_at = time.monotonic()
            return True

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

    def repair_audio(
        self,
        *,
        before_restart: Callable[[], None] | None = None,
        after_restart: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        status = self._start_repair_task(
            before_restart=before_restart,
            after_restart=after_restart,
        )
        response = status.to_dict()
        with self._audio_task_lock:
            response["restart_id"] = (
                self._active_restart_id
                if self._active_restart_id is not None
                else self._completed_restart_id
            )
        return response

    def _start_repair_task(
        self,
        *,
        before_restart: Callable[[], None] | None = None,
        after_restart: Callable[[], None] | None = None,
    ) -> AudioStatus:
        with self._status_commit_lock:
            with self._audio_task_lock:
                if self._repair_task_running:
                    return AudioStatus(
                        last_error="DeckSoundpad restart already running",
                        state="repairing",
                    )
                self._repair_task_running = True
                self._repair_done.clear()
                self._audio_generation += 1
                generation = self._audio_generation
                self._restart_sequence += 1
                restart_id = self._restart_sequence
                self._active_restart_id = restart_id

        started_status = AudioStatus(
            last_error="DeckSoundpad restart started",
            state="repairing",
        )
        try:
            self.publish_progress_status(
                started_status,
                expected_generation=generation,
            )
        except Exception:
            with self._status_commit_lock:
                with self._audio_task_lock:
                    self._repair_task_running = False
                    self._active_restart_id = None
                    self._repair_done.set()
            raise

        def run() -> None:
            status = AudioStatus(
                last_error="DeckSoundpad restart interrupted", state="error"
            )
            failures: list[str] = []
            try:
                self.logger.info("DeckSoundpad runtime restart started")
                if before_restart is not None:
                    try:
                        before_restart()
                    except Exception as exc:
                        self.logger.exception("DeckSoundpad bridge teardown failed")
                        failures.append(f"bridge teardown failed: {exc}")
                try:
                    status = self._restart_runtime()
                    self.logger.info(
                        "DeckSoundpad runtime restart finished status=%s",
                        status.to_dict(),
                    )
                except Exception as exc:
                    self.logger.exception("DeckSoundpad runtime restart failed")
                    failures.append(f"runtime restart failed: {exc}")
                if after_restart is not None:
                    try:
                        after_restart()
                    except Exception as exc:
                        self.logger.exception(
                            "DeckSoundpad bridge reinitialization failed"
                        )
                        failures.append(f"bridge reinitialization failed: {exc}")
                if failures:
                    status = AudioStatus(
                        last_error="DeckSoundpad restart failed: "
                        + "; ".join(failures),
                        state="error",
                    )
            finally:
                self._remember_playback_route_status(
                    status,
                    expected_generation=generation,
                )
                try:
                    self.publish_status(
                        status,
                        expected_generation=generation,
                        allow_during_restart=True,
                    )
                except Exception:
                    self.logger.exception(
                        "failed to publish DeckSoundpad restart status"
                    )
                    try:
                        self.publish_progress_status(
                            status,
                            expected_generation=generation,
                        )
                    except Exception:
                        self.logger.exception(
                            "failed to publish fallback restart status"
                        )
                finally:
                    with self._status_commit_lock:
                        with self._audio_task_lock:
                            self._repair_task_running = False
                            if self._active_restart_id == restart_id:
                                self._completed_restart_id = restart_id
                                self._active_restart_id = None
                            self._repair_done.set()

        threading.Thread(
            target=run, name="decksoundpad-runtime-restart", daemon=True
        ).start()
        return started_status

    def _restart_runtime(self) -> AudioStatus:
        with self._runtime_lock:
            new_settings = load_config(self.paths)
            new_library, new_router, new_player = self._create_runtime_components(
                new_settings
            )
            old_player = self.player
            old_router = self.router
            cleanup_failures: list[str] = []
            try:
                self._close_runtime_player(old_player, strict=True)
            except Exception as exc:
                cleanup_failures.append(f"playback cleanup failed: {exc}")
            try:
                self._teardown_runtime_router(old_router, strict=True)
            except Exception as exc:
                cleanup_failures.append(f"audio route cleanup failed: {exc}")
            if cleanup_failures:
                self._close_runtime_player(new_player)
                self._teardown_runtime_router(new_router)
                raise RuntimeError("; ".join(cleanup_failures))
            self.settings = new_settings
            self.library = new_library
            self.router = new_router
            self.player = new_player
            self._forget_playback_route_status()
            try:
                return self._final_audio_status(self.router.ensure())
            finally:
                self.library.scan()

    def _close_runtime_player(self, player: Any, *, strict: bool = False) -> None:
        try:
            close = getattr(player, "close", None)
            if callable(close):
                close()
            else:
                player.stop_all()
        except Exception:
            self.logger.exception("failed to stop old playback runtime during restart")
            if strict:
                raise

    def _teardown_runtime_router(self, router: Any, *, strict: bool = False) -> None:
        teardown = getattr(router, "teardown", None)
        if not callable(teardown):
            return
        try:
            teardown()
        except Exception:
            self.logger.exception("failed to tear down old audio route during restart")
            if strict:
                raise

    def close(self) -> None:
        self._repair_done.wait()
        with self._runtime_lock:
            self._close_runtime_player(self.player)
            self._teardown_runtime_router(self.router)

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
        with self._status_commit_lock:
            with self._audio_task_lock:
                self._audio_generation += 1
                generation = self._audio_generation
        previous_mic_passthrough = self.settings.mic_passthrough_enabled
        previous_mic_volume = self.settings.mic_passthrough_volume
        next_settings = patch_settings(self.settings, patch)
        library = SoundLibrary(self.paths, next_settings)
        if LIBRARY_SETTING_KEYS & patch.keys():
            # Scan before saving: an unusable folder is rejected and the old
            # library stays active, and the on-disk cache never lists sounds
            # from the previous folders.
            library.scan()
        self.settings = next_settings
        save_config(self.paths, self.settings)
        self.library = library
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
                if (
                    self.settings.mic_passthrough_enabled
                    and self.settings.mic_passthrough_volume != previous_mic_volume
                    and not self.router.apply_mic_passthrough_volume()
                ):
                    self.logger.warning(
                        "mic passthrough volume not applied volume=%.2f",
                        self.settings.mic_passthrough_volume,
                    )
                status = self.router.healthcheck()
        self._remember_playback_route_status(
            status,
            expected_generation=generation,
        )
        self.publish_status(
            status,
            expected_generation=generation,
            allow_during_restart=True,
        )
        return self.settings_payload()

    def run_healthcheck_cycle(self) -> AudioStatus | None:
        with self._audio_task_lock:
            if self._repair_task_running:
                return None
            generation = self._audio_generation
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
            self._remember_playback_route_status(
                status,
                expected_generation=generation,
            )
        self.publish_status(status, expected_generation=generation)
        return status

    def best_backend_name(self) -> str | None:
        probes = [
            Path(f"probe{extension}") for extension in self.settings.allowed_extensions
        ]
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


def start_healthcheck_loop(
    app: DeckSoundpadApp, interval_seconds: float = 8.0
) -> threading.Event:
    stop_event = threading.Event()

    def run() -> None:
        while not stop_event.wait(interval_seconds):
            try:
                app.run_healthcheck_cycle()
            except Exception:
                # The bridge only restarts this loop once it is stopped, so an
                # escaped error (such as a failed auto repair) would end it for good.
                app.logger.exception("background healthcheck cycle failed")

    thread = threading.Thread(target=run, name="decksoundpad-healthcheck", daemon=True)
    setattr(stop_event, "_decksoundpad_thread", thread)
    thread.start()
    return stop_event
