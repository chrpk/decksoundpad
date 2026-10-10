from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.app import DeckSoundpadApp, start_healthcheck_loop
from decksoundpad.config import Settings
from decksoundpad.models import AudioStatus
from decksoundpad.paths import AppPaths


class FakeRouter:
    def healthcheck(self) -> AudioStatus:
        return AudioStatus(
            pipewire_available=True,
            pactl_available=True,
            sink_exists=True,
            virtual_mic_exists=True,
            loopback_exists=True,
            selected_real_mic="alsa_input.test",
            default_source="decksoundpad_mic",
            is_default_source=True,
        )

    def ensure(self) -> AudioStatus:
        return self.healthcheck()

    def repair(self) -> AudioStatus:
        return self.healthcheck()


class MicVolumeRouter(FakeRouter):
    def __init__(self) -> None:
        self.mic_volume_calls = 0

    def apply_mic_passthrough_volume(self) -> bool:
        self.mic_volume_calls += 1
        return True


class CountingRouter(FakeRouter):
    def __init__(self) -> None:
        self.healthcheck_calls = 0

    def healthcheck(self) -> AudioStatus:
        self.healthcheck_calls += 1
        return super().healthcheck()


class RouteRepairRouter(FakeRouter):
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.ready = False

    def healthcheck(self) -> AudioStatus:
        if self.ready:
            return super().healthcheck()
        return AudioStatus(
            pipewire_available=True,
            pactl_available=True,
            sink_exists=False,
            virtual_mic_exists=False,
            state="needs_repair",
        )

    def ensure(self) -> AudioStatus:
        self.ensure_calls += 1
        self.ready = True
        return self.healthcheck()


class BrokenRouteRouter(RouteRepairRouter):
    def ensure(self) -> AudioStatus:
        self.ensure_calls += 1
        return AudioStatus(
            pipewire_available=True,
            pactl_available=True,
            sink_exists=False,
            virtual_mic_exists=False,
            last_error="DeckSoundpad internal mix bus did not appear",
            state="error",
        )


class FakeBackend:
    name = "fake"

    def is_available(self) -> bool:
        return True

    def can_play(self, _path: Path) -> bool:
        return True


class RecordingPlayer:
    def __init__(self) -> None:
        self.backends = [FakeBackend()]
        self.play_calls: list[tuple[str, Path, float | None]] = []

    def play(
        self,
        sound_id: str,
        path: Path,
        volume: float | None = None,
    ) -> str:
        self.play_calls.append((sound_id, path, volume))
        return "pb_test"

    def stop_all(self) -> None:
        return None


class RestartTrackingRouter(FakeRouter):
    def __init__(self) -> None:
        self.teardown_calls = 0
        self.ensure_calls = 0

    def teardown(self) -> None:
        self.teardown_calls += 1

    def ensure(self) -> AudioStatus:
        self.ensure_calls += 1
        return self.healthcheck()


class BlockingEnsureRouter(RestartTrackingRouter):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def ensure(self) -> AudioStatus:
        self.ensure_calls += 1
        self.started.set()
        self.release.wait(timeout=2)
        return self.healthcheck()


class RestartTrackingPlayer:
    def __init__(self) -> None:
        self.backends = [FakeBackend()]
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    def stop_all(self) -> None:
        return None


class RestartTrackingLibrary:
    def __init__(self) -> None:
        self.scan_calls = 0

    def roots(self) -> list[Path]:
        return []

    def cached_items(self) -> list[object]:
        return []

    def scan(self) -> list[object]:
        self.scan_calls += 1
        return []


class FailingRestartLibrary(RestartTrackingLibrary):
    def cached_items(self) -> list[object]:
        raise RuntimeError("library cache unavailable")

    def scan(self) -> list[object]:
        raise RuntimeError("library scan unavailable")


def make_paths(root: Path) -> AppPaths:
    plugin = root / "plugin"
    (plugin / "defaults").mkdir(parents=True)
    (plugin / "defaults" / "config.default.json").write_text(
        json.dumps({"library_dirs": [str(root / "sounds")]}),
        encoding="utf-8",
    )
    return AppPaths(
        plugin_dir=plugin,
        settings_dir=root / "settings",
        runtime_dir=root / "runtime",
        log_dir=root / "logs",
        user_home=root / "home",
    )


class AppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = make_paths(Path(self.tmp.name))
        self.app = DeckSoundpadApp(self.paths)
        self.app.router = FakeRouter()  # type: ignore[assignment]
        self.app.player.backends = [FakeBackend()]  # type: ignore[list-item]

    def tearDown(self) -> None:
        self.app.player.stop_all()
        self.tmp.cleanup()

    def test_status(self) -> None:
        response = self.app.status()
        self.assertTrue(response["backend_running"])
        self.assertEqual(response["player"]["backend"], "fake")  # type: ignore[index]

    def test_quick_status_does_not_probe_audio(self) -> None:
        router = CountingRouter()
        self.app.router = router  # type: ignore[assignment]
        response = self.app.quick_status()
        self.assertTrue(response["backend_running"])
        self.assertEqual(response["audio"]["last_error"], "Audio status pending")  # type: ignore[index]
        self.assertEqual(router.healthcheck_calls, 0)

    def test_settings_patch_persists(self) -> None:
        response = self.app.update_settings({"master_volume": 0.75})
        self.assertEqual(response["master_volume"], 0.75)
        self.assertIn('"master_volume": 0.75', self.paths.config_file.read_text())

    def test_mic_passthrough_volume_change_applies_to_running_loopback(self) -> None:
        router = MicVolumeRouter()
        with patch("decksoundpad.app.AudioRouter", return_value=router):
            response = self.app.update_settings({"mic_passthrough_volume": 1.4})
            self.app.update_settings({"master_volume": 1.2})

        self.assertEqual(response["mic_passthrough_volume"], 1.4)
        self.assertEqual(router.mic_volume_calls, 1)

    def test_mic_passthrough_volume_change_skips_disabled_passthrough(self) -> None:
        router = MicVolumeRouter()
        with patch("decksoundpad.app.AudioRouter", return_value=router):
            self.app.update_settings({"mic_passthrough_enabled": False})
            response = self.app.update_settings({"mic_passthrough_volume": 0.5})

        self.assertEqual(response["mic_passthrough_volume"], 0.5)
        self.assertEqual(router.mic_volume_calls, 0)

    def test_playing_sound_ids_and_stop_all_sounds_use_the_player(self) -> None:
        player = MagicMock()
        player.active_sound_ids.return_value = {"sound-a"}
        self.app.player = player  # type: ignore[assignment]

        self.assertEqual(self.app.playing_sound_ids(), frozenset({"sound-a"}))
        self.assertEqual(self.app.stop_all_sounds(), {"ok": True})
        player.stop_all.assert_called_once_with()

    def test_playing_sound_ids_does_not_wait_behind_busy_playback(self) -> None:
        holding = threading.Event()
        release = threading.Event()

        def hold_runtime_lock() -> None:
            with self.app._runtime_lock:
                holding.set()
                release.wait(timeout=2.0)

        holder = threading.Thread(target=hold_runtime_lock)
        holder.start()
        try:
            self.assertTrue(holding.wait(timeout=1.0))
            self.assertIsNone(self.app.playing_sound_ids(timeout=0.01))
        finally:
            release.set()
            holder.join(timeout=2.0)

    def test_play_rejects_unknown_sound_id(self) -> None:
        response = self.app.play_sound({"sound_id": "sha1:nope"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "sound not found")

    def test_play_test_sound_plays_generated_beep_through_route(self) -> None:
        router = RouteRepairRouter()
        player = RecordingPlayer()
        self.app.router = router  # type: ignore[assignment]
        self.app.player = player  # type: ignore[assignment]

        response = self.app.play_test_sound()

        self.assertTrue(response["ok"])
        self.assertEqual(response["sound_id"], "test_beep")
        self.assertEqual(response["route"]["sink"], "decksoundpad_sink")
        self.assertEqual(
            player.play_calls, [("test_beep", self.paths.test_beep_file, None)]
        )
        with wave.open(str(self.paths.test_beep_file), "rb") as beep:
            self.assertEqual(beep.getframerate(), 48000)
            self.assertEqual(beep.getnchannels(), 2)
            self.assertEqual(beep.getsampwidth(), 2)
            self.assertGreater(beep.getnframes(), 0)

    def test_play_test_sound_reuses_an_unchanged_beep_file(self) -> None:
        self.app.router = RouteRepairRouter()  # type: ignore[assignment]
        self.app.player = RecordingPlayer()  # type: ignore[assignment]
        self.app.play_test_sound()
        beep = self.paths.test_beep_file
        os.utime(beep, ns=(1_000_000_000, 1_000_000_000))

        self.app.play_test_sound()
        # Unchanged content keeps its mtime, so the mixer's decoded copy stays valid.
        self.assertEqual(beep.stat().st_mtime_ns, 1_000_000_000)

        beep.write_bytes(b"not a wav")
        self.app.play_test_sound()
        with wave.open(str(beep), "rb") as restored:
            self.assertGreater(restored.getnframes(), 0)

    def test_healthcheck_loop_survives_a_failed_cycle(self) -> None:
        app = MagicMock()
        recovered = threading.Event()
        cycles: list[int] = []

        def cycle() -> None:
            cycles.append(1)
            if len(cycles) == 1:
                raise RuntimeError("auto repair failed")
            recovered.set()

        app.run_healthcheck_cycle.side_effect = cycle
        stop = start_healthcheck_loop(app, interval_seconds=0.01)
        try:
            self.assertTrue(recovered.wait(2.0))
        finally:
            stop.set()
            getattr(stop, "_decksoundpad_thread").join(timeout=1.0)
        app.logger.exception.assert_called_once()

    def test_play_test_sound_returns_route_error(self) -> None:
        self.app.router = BrokenRouteRouter()  # type: ignore[assignment]
        player = RecordingPlayer()
        self.app.player = player  # type: ignore[assignment]

        response = self.app.play_test_sound()

        self.assertFalse(response["ok"])
        self.assertEqual(
            response["error"], "DeckSoundpad internal mix bus did not appear"
        )
        self.assertEqual(player.play_calls, [])

    def test_refresh_library_does_not_touch_audio_playback(self) -> None:
        player = RecordingPlayer()
        self.app.player = player  # type: ignore[assignment]
        sounds_dir = Path(self.tmp.name) / "sounds"
        sounds_dir.mkdir()
        (sounds_dir / "test.wav").write_bytes(b"wav")

        response = self.app.refresh_library()

        self.assertTrue(response["ok"])
        self.assertEqual(player.play_calls, [])

    def test_set_library_folder_rescans_new_folder_and_persists(self) -> None:
        old_dir = Path(self.tmp.name) / "sounds"
        old_dir.mkdir()
        (old_dir / "old.wav").write_bytes(b"wav")
        self.app.refresh_library()
        new_dir = Path(self.tmp.name) / "other"
        new_dir.mkdir()
        (new_dir / "new.wav").write_bytes(b"wav")

        response = self.app.set_library_folder(str(new_dir))

        self.assertTrue(response["ok"])
        self.assertEqual(response["settings"]["library_dirs"], [str(new_dir)])  # type: ignore[index]
        self.assertEqual(
            [sound["display_name"] for sound in response["sounds"]],  # type: ignore[index]
            ["new"],
        )
        self.assertEqual(
            [sound["display_name"] for sound in self.app.list_sounds()["sounds"]],
            ["new"],
        )
        self.assertIn(str(new_dir), self.paths.config_file.read_text())
        self.assertNotIn("old.wav", self.paths.library_cache_file.read_text())
        library = self.app.quick_status()["library"]
        self.assertEqual(library["count"], 1)  # type: ignore[index]
        self.assertEqual(library["dirs"], [str(new_dir)])  # type: ignore[index]

    def test_set_library_folder_rejects_unusable_folder_and_keeps_library(self) -> None:
        old_dir = Path(self.tmp.name) / "sounds"
        old_dir.mkdir()
        (old_dir / "old.wav").write_bytes(b"wav")
        self.app.refresh_library()
        not_a_folder = Path(self.tmp.name) / "file.wav"
        not_a_folder.write_bytes(b"wav")

        for folder in ("relative/sounds", str(not_a_folder)):
            with self.subTest(folder=folder):
                response = self.app.set_library_folder(folder)

                self.assertFalse(response["ok"])
                self.assertTrue(response["error"])
                self.assertEqual(response["settings"]["library_dirs"], [str(old_dir)])  # type: ignore[index]
                self.assertEqual(self.app.settings.library_dirs, [str(old_dir)])
                self.assertEqual(
                    [
                        sound["display_name"]
                        for sound in self.app.list_sounds()["sounds"]
                    ],
                    ["old"],
                )
                self.assertIn("old.wav", self.paths.library_cache_file.read_text())

    def test_settings_patch_of_library_dirs_rescans_library(self) -> None:
        old_dir = Path(self.tmp.name) / "sounds"
        old_dir.mkdir()
        (old_dir / "old.wav").write_bytes(b"wav")
        self.app.refresh_library()
        new_dir = Path(self.tmp.name) / "other"
        new_dir.mkdir()
        (new_dir / "new.wav").write_bytes(b"wav")

        self.app.update_settings({"library_dirs": [str(new_dir)]})

        self.assertEqual(
            [sound["display_name"] for sound in self.app.list_sounds()["sounds"]],
            ["new"],
        )

    def test_play_returns_clean_error_without_backend(self) -> None:
        self.app.player.backends = []
        sounds_dir = Path(self.tmp.name) / "sounds"
        sounds_dir.mkdir()
        (sounds_dir / "test.wav").write_bytes(b"wav")
        sounds = self.app.refresh_library()["sounds"]
        sound_id = sounds[0]["id"]
        response = self.app.play_sound({"sound_id": sound_id})
        self.assertFalse(response["ok"])
        self.assertIn("no playback backend", str(response["error"]))

    def test_play_ensures_audio_route_before_spawning_player(self) -> None:
        router = RouteRepairRouter()
        player = RecordingPlayer()
        self.app.router = router  # type: ignore[assignment]
        self.app.player = player  # type: ignore[assignment]
        sounds_dir = Path(self.tmp.name) / "sounds"
        sounds_dir.mkdir()
        (sounds_dir / "test.wav").write_bytes(b"wav")
        sounds = self.app.refresh_library()["sounds"]
        sound_id = sounds[0]["id"]

        response = self.app.play_sound({"sound_id": sound_id})

        self.assertTrue(response["ok"])
        self.assertEqual(response["backend"], "fake")
        self.assertEqual(response["route"]["sink"], "decksoundpad_sink")
        self.assertEqual(response["route"]["virtual_input"], "decksoundpad_mic")
        self.assertEqual(router.ensure_calls, 1)
        self.assertEqual(len(player.play_calls), 1)
        self.assertEqual(player.play_calls[0][0], sound_id)

    def test_play_uses_recent_ready_route_cache(self) -> None:
        router = CountingRouter()
        player = RecordingPlayer()
        self.app.router = router  # type: ignore[assignment]
        self.app.player = player  # type: ignore[assignment]
        sounds_dir = Path(self.tmp.name) / "sounds"
        sounds_dir.mkdir()
        (sounds_dir / "test.wav").write_bytes(b"wav")
        sounds = self.app.refresh_library()["sounds"]
        sound_id = sounds[0]["id"]

        status = self.app.status()
        self.assertTrue(status["backend_running"])
        router.healthcheck_calls = 0
        response = self.app.play_sound({"sound_id": sound_id})

        self.assertTrue(response["ok"])
        self.assertEqual(response["route"]["mode"], "stream_to_internal_sink")
        self.assertEqual(router.healthcheck_calls, 0)
        self.assertEqual(len(player.play_calls), 1)

    def test_play_returns_route_error_without_spawning_player(self) -> None:
        router = BrokenRouteRouter()
        player = RecordingPlayer()
        self.app.router = router  # type: ignore[assignment]
        self.app.player = player  # type: ignore[assignment]
        sounds_dir = Path(self.tmp.name) / "sounds"
        sounds_dir.mkdir()
        (sounds_dir / "test.wav").write_bytes(b"wav")
        sounds = self.app.refresh_library()["sounds"]
        sound_id = sounds[0]["id"]

        response = self.app.play_sound({"sound_id": sound_id})

        self.assertFalse(response["ok"])
        self.assertEqual(
            response["error"], "DeckSoundpad internal mix bus did not appear"
        )
        self.assertEqual(router.ensure_calls, 1)
        self.assertEqual(player.play_calls, [])

    def test_audio_repair_restarts_all_runtime_components(self) -> None:
        old_router = RestartTrackingRouter()
        old_player = RestartTrackingPlayer()
        new_router = RestartTrackingRouter()
        new_player = RestartTrackingPlayer()
        new_library = RestartTrackingLibrary()
        self.app.router = old_router  # type: ignore[assignment]
        self.app.player = old_player  # type: ignore[assignment]
        self.app._audio_task_running = True

        with (
            patch("decksoundpad.app.load_config", return_value=Settings()),
            patch("decksoundpad.app.SoundLibrary", return_value=new_library),
            patch("decksoundpad.app.AudioRouter", return_value=new_router),
            patch("decksoundpad.app.PlaybackManager", return_value=new_player),
        ):
            response = self.app.repair_audio()
            deadline = time.monotonic() + 2
            final_status = response
            while time.monotonic() < deadline:
                final_status = self.app.quick_status()["audio"]  # type: ignore[assignment]
                if final_status["state"] != "repairing":
                    break
                time.sleep(0.02)

        self.assertEqual(response["last_error"], "DeckSoundpad restart started")
        self.assertEqual(response["state"], "repairing")
        self.assertEqual(old_player.close_calls, 1)
        self.assertEqual(old_router.teardown_calls, 1)
        self.assertIs(self.app.router, new_router)
        self.assertIs(self.app.player, new_player)
        self.assertIs(self.app.library, new_library)
        self.assertEqual(new_router.ensure_calls, 1)
        self.assertEqual(new_library.scan_calls, 1)
        self.assertEqual(final_status["state"], "ready")

    def test_quick_status_stays_repairing_when_stale_ready_status_is_published(
        self,
    ) -> None:
        restart_started = threading.Event()
        allow_restart = threading.Event()

        def restart() -> AudioStatus:
            restart_started.set()
            self.assertTrue(allow_restart.wait(timeout=1.0))
            return AudioStatus(state="ready")

        with patch.object(self.app, "_restart_runtime", side_effect=restart):
            response = self.app.repair_audio()
            self.assertTrue(restart_started.wait(timeout=1.0))
            self.app.publish_status(AudioStatus(state="ready"))
            status = self.app.quick_status()
            allow_restart.set()
            self.assertTrue(self.app._repair_done.wait(timeout=1.0))

        self.assertEqual(response["state"], "repairing")
        self.assertTrue(status["restart_running"])
        self.assertEqual(status["audio"]["state"], "repairing")
        final_status = self.app.quick_status()
        self.assertFalse(final_status["restart_running"])
        self.assertEqual(final_status["restart_completed_id"], response["restart_id"])

    def test_settings_update_status_wins_over_stale_restart_completion(self) -> None:
        restart_started = threading.Event()
        allow_restart = threading.Event()

        def restart() -> AudioStatus:
            restart_started.set()
            self.assertTrue(allow_restart.wait(timeout=1.0))
            return AudioStatus(state="ready")

        settings_status = AudioStatus(
            last_error="settings runtime status",
            state="needs_repair",
        )
        with (
            patch.object(self.app, "_restart_runtime", side_effect=restart),
            patch(
                "decksoundpad.app.AudioRouter.healthcheck", return_value=settings_status
            ),
        ):
            self.app.repair_audio()
            self.assertTrue(restart_started.wait(timeout=1.0))
            self.app.update_settings({"master_volume": 0.8})
            self.assertFalse(self.app._repair_done.is_set())
            allow_restart.set()
            self.assertTrue(self.app._repair_done.wait(timeout=1.0))

        with self.app._audio_task_lock:
            self.assertFalse(self.app._repair_task_running)
        final_status = self.app.quick_status()
        self.assertEqual(final_status["audio"]["state"], "needs_repair")
        self.assertEqual(final_status["audio"]["last_error"], "settings runtime status")
        self.assertEqual(self.app._playback_route_status, settings_status)

    def test_initial_progress_publication_failure_does_not_wedge_restart(self) -> None:
        with patch.object(
            self.app,
            "publish_progress_status",
            side_effect=RuntimeError("cache unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "cache unavailable"):
                self.app.repair_audio()

        with self.app._audio_task_lock:
            self.assertFalse(self.app._repair_task_running)
        self.assertTrue(self.app._repair_done.is_set())

    def test_cleanup_failure_keeps_old_runtime_and_reports_error(self) -> None:
        old_router = RestartTrackingRouter()
        old_player = RestartTrackingPlayer()
        old_player.close = MagicMock(side_effect=RuntimeError("player close failed"))
        new_router = RestartTrackingRouter()
        new_player = RestartTrackingPlayer()
        new_library = RestartTrackingLibrary()
        self.app.router = old_router  # type: ignore[assignment]
        self.app.player = old_player  # type: ignore[assignment]

        with (
            patch("decksoundpad.app.load_config", return_value=Settings()),
            patch("decksoundpad.app.SoundLibrary", return_value=new_library),
            patch("decksoundpad.app.AudioRouter", return_value=new_router),
            patch("decksoundpad.app.PlaybackManager", return_value=new_player),
        ):
            self.app.repair_audio()
            self.assertTrue(self.app._repair_done.wait(timeout=1.0))

        self.assertIs(self.app.router, old_router)
        self.assertIs(self.app.player, old_player)
        self.assertEqual(self.app.quick_status()["audio"]["state"], "error")
        self.assertIn(
            "player close failed",
            self.app.quick_status()["audio"]["last_error"],
        )

    def test_close_waits_for_runtime_restart_before_closing_resources(self) -> None:
        restart_started = threading.Event()
        allow_restart = threading.Event()

        def restart() -> AudioStatus:
            restart_started.set()
            self.assertTrue(allow_restart.wait(timeout=1.0))
            return AudioStatus(state="ready")

        with (
            patch.object(self.app, "_restart_runtime", side_effect=restart),
            patch.object(self.app, "_close_runtime_player") as close_player,
            patch.object(self.app, "_teardown_runtime_router") as teardown_router,
        ):
            self.app.repair_audio()
            self.assertTrue(restart_started.wait(timeout=1.0))
            close_thread = threading.Thread(target=self.app.close)
            close_thread.start()
            time.sleep(0.02)
            close_player.assert_not_called()
            allow_restart.set()
            close_thread.join(timeout=1.0)

        self.assertFalse(close_thread.is_alive())
        close_player.assert_called_once_with(self.app.player)
        teardown_router.assert_called_once_with(self.app.router)

    def test_audio_repair_runs_bridge_reinitialization_after_runtime_failure(
        self,
    ) -> None:
        events: list[str] = []
        with patch.object(
            self.app, "_restart_runtime", side_effect=RuntimeError("boom")
        ):
            response = self.app.repair_audio(
                before_restart=lambda: events.append("before"),
                after_restart=lambda: events.append("after"),
            )
            self.assertEqual(response["state"], "repairing")
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                with self.app._audio_task_lock:
                    if not self.app._repair_task_running:
                        break
                time.sleep(0.01)

        self.assertEqual(events, ["before", "after"])
        self.assertFalse(self.app._repair_task_running)
        self.assertEqual(self.app.quick_status()["audio"]["state"], "error")
        self.assertIn(
            "runtime restart failed: boom",
            self.app.quick_status()["audio"]["last_error"],
        )

    def test_audio_repair_clears_restart_flag_when_status_publication_fails(
        self,
    ) -> None:
        router = RestartTrackingRouter()
        library = FailingRestartLibrary()
        player = RestartTrackingPlayer()
        with (
            patch("decksoundpad.app.load_config", return_value=Settings()),
            patch("decksoundpad.app.SoundLibrary", return_value=library),
            patch("decksoundpad.app.AudioRouter", return_value=router),
            patch("decksoundpad.app.PlaybackManager", return_value=player),
        ):
            self.app.repair_audio()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                with self.app._audio_task_lock:
                    if not self.app._repair_task_running:
                        break
                time.sleep(0.02)

        with self.app._audio_task_lock:
            self.assertFalse(self.app._repair_task_running)
        self.assertEqual(self.app.quick_status()["audio"]["state"], "error")  # type: ignore[index]

    def test_audio_repair_stays_responsive_while_route_check_is_blocked(self) -> None:
        old_router = BlockingEnsureRouter()
        new_router = BlockingEnsureRouter()
        library = RestartTrackingLibrary()
        player = RestartTrackingPlayer()
        self.app.router = old_router  # type: ignore[assignment]
        self.app._schedule_playback_route_check()
        self.assertTrue(old_router.started.wait(timeout=1))
        release_old = threading.Timer(0.3, old_router.release.set)
        release_old.start()

        with (
            patch("decksoundpad.app.load_config", return_value=Settings()),
            patch("decksoundpad.app.SoundLibrary", return_value=library),
            patch("decksoundpad.app.AudioRouter", return_value=new_router),
            patch("decksoundpad.app.PlaybackManager", return_value=player),
        ):
            started_at = time.monotonic()
            response = self.app.repair_audio()
            elapsed = time.monotonic() - started_at
            self.assertLess(elapsed, 0.1)
            self.assertEqual(response["state"], "repairing")
            self.assertTrue(new_router.started.wait(timeout=1))
            self.assertEqual(self.app.quick_status()["audio"]["state"], "repairing")  # type: ignore[index]
            new_router.release.set()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if self.app.quick_status()["audio"]["state"] != "repairing":  # type: ignore[index]
                    break
                time.sleep(0.02)

        release_old.join(timeout=1)
        self.assertEqual(self.app.quick_status()["audio"]["state"], "ready")  # type: ignore[index]

    def test_audio_repair_returns_before_blocking_router_finishes(self) -> None:
        router = BlockingEnsureRouter()
        library = RestartTrackingLibrary()
        player = RestartTrackingPlayer()
        started_at = time.monotonic()
        with (
            patch("decksoundpad.app.load_config", return_value=Settings()),
            patch("decksoundpad.app.SoundLibrary", return_value=library),
            patch("decksoundpad.app.AudioRouter", return_value=router),
            patch("decksoundpad.app.PlaybackManager", return_value=player),
        ):
            response = self.app.repair_audio()
            elapsed = time.monotonic() - started_at
            self.assertLess(elapsed, 0.5)
            self.assertEqual(response["last_error"], "DeckSoundpad restart started")
            self.assertEqual(response["state"], "repairing")
            self.assertTrue(router.started.wait(timeout=1))
            router.release.set()
            deadline = time.monotonic() + 1
            final_status = response
            while time.monotonic() < deadline:
                final_response = self.app.quick_status()
                final_status = final_response["audio"]  # type: ignore[assignment]
                if final_status["state"] != "repairing":
                    break
                time.sleep(0.05)

        self.assertEqual(final_status["state"], "ready")
        self.assertIsNone(final_status["last_error"])


if __name__ == "__main__":
    unittest.main()
