from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.app import DeckSoundpadApp
from decksoundpad.models import AudioProbe, AudioStatus
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

    def probe(self) -> AudioProbe:
        return AudioProbe(
            pipewire_available=True,
            pactl_available=True,
            pw_play_available=True,
            ffmpeg_available=False,
            mpv_available=False,
        )

    def ensure(self) -> AudioStatus:
        return self.healthcheck()

    def repair(self) -> AudioStatus:
        return self.healthcheck()


class CountingRouter(FakeRouter):
    def __init__(self) -> None:
        self.healthcheck_calls = 0

    def healthcheck(self) -> AudioStatus:
        self.healthcheck_calls += 1
        return super().healthcheck()


class BlockingRouter(FakeRouter):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def repair(self) -> AudioStatus:
        self.started.set()
        self.release.wait(timeout=2)
        return self.healthcheck()


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
        self.preload_calls: list[list[Path]] = []

    def active_count(self) -> int:
        return 0

    def play(
        self,
        sound_id: str,
        path: Path,
        volume: float | None = None,
    ) -> str:
        self.play_calls.append((sound_id, path, volume))
        return "pb_test"

    def preload(self, paths: list[Path]) -> None:
        self.preload_calls.append(paths)

    def stop_playback(self, _playback_id: str) -> None:
        return None

    def stop_sound(self, _sound_id: str) -> None:
        return None

    def stop_all(self) -> None:
        return None


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

    def test_play_rejects_unknown_sound_id(self) -> None:
        response = self.app.play_sound({"sound_id": "sha1:nope"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "sound not found")

    def test_refresh_library_does_not_preload_or_touch_audio_playback(self) -> None:
        player = RecordingPlayer()
        self.app.player = player  # type: ignore[assignment]
        sounds_dir = Path(self.tmp.name) / "sounds"
        sounds_dir.mkdir()
        (sounds_dir / "test.wav").write_bytes(b"wav")

        response = self.app.refresh_library()

        self.assertTrue(response["ok"])
        self.assertEqual(player.preload_calls, [])

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
        self.assertEqual(response["error"], "DeckSoundpad internal mix bus did not appear")
        self.assertEqual(router.ensure_calls, 1)
        self.assertEqual(player.play_calls, [])

    def test_audio_repair_returns_before_blocking_router_finishes(self) -> None:
        router = BlockingRouter()
        self.app.router = router  # type: ignore[assignment]
        started_at = time.monotonic()
        response = self.app.repair_audio()
        elapsed = time.monotonic() - started_at
        self.assertLess(elapsed, 0.5)
        self.assertEqual(response["last_error"], "Audio repair started")
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
