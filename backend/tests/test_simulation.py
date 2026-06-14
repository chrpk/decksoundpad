from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.api_server import DeckSoundpadApp
from decksoundpad.paths import AppPaths
from decksoundpad.simulation import SimulatedAudioRouter, SimulatedPlaybackManager, simulation_enabled


def make_paths(root: Path) -> AppPaths:
    plugin = root / "plugin"
    bundled = plugin / "defaults" / "sounds" / "sample"
    bundled.mkdir(parents=True)
    (bundled / "ready.wav").write_bytes(b"wav")
    (plugin / "defaults" / "config.default.json").write_text(
        json.dumps(
            {
                "library_dirs": [str(root / "sounds")],
                "web_host": "127.0.0.1",
                "web_port": 8787,
                "auth_enabled": True,
                "max_concurrent_sounds": 2,
            }
        ),
        encoding="utf-8",
    )
    return AppPaths(
        plugin_dir=plugin,
        settings_dir=root / "settings",
        runtime_dir=root / "runtime",
        log_dir=root / "logs",
        data_dir=root / "data",
        user_home=root / "home",
    )


class SimulationTests(unittest.TestCase):
    def test_simulation_enabled_env_values(self) -> None:
        self.assertTrue(simulation_enabled({"DECKSOUNDPAD_SIMULATE": "1"}))
        self.assertTrue(simulation_enabled({"DECKSOUNDPAD_SIMULATE": "true"}))
        self.assertFalse(simulation_enabled({"DECKSOUNDPAD_SIMULATE": "0"}))
        self.assertFalse(simulation_enabled({}))

    def test_app_uses_simulated_audio_and_player(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DECKSOUNDPAD_SIMULATE": "1"}):
                app = DeckSoundpadApp(make_paths(Path(tmp)))

            self.assertTrue(app.simulation)
            self.assertIsInstance(app.router, SimulatedAudioRouter)
            self.assertIsInstance(app.player, SimulatedPlaybackManager)

            status = app.status()
            self.assertTrue(status["daemon_running"])
            self.assertEqual(status["player"]["backend"], "simulated")
            self.assertTrue(status["audio"]["sink_exists"])
            self.assertTrue(status["audio"]["virtual_mic_exists"])
            self.assertEqual(status["audio"]["selected_real_mic"], "simulated_real_mic")

    def test_simulated_play_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DECKSOUNDPAD_SIMULATE": "1"}):
                app = DeckSoundpadApp(make_paths(Path(tmp)))

            sounds = app.refresh_library()["sounds"]
            self.assertEqual(len(sounds), 1)
            sound_id = sounds[0]["id"]

            play_response = app.play_sound({"sound_id": sound_id, "volume": 0.5})
            self.assertTrue(play_response["ok"])
            self.assertTrue(str(play_response["playback_id"]).startswith("sim_pb_"))
            self.assertEqual(app.player.active_count(), 1)

            stop_response = app.stop({"playback_id": None, "sound_id": None})
            self.assertTrue(stop_response["ok"])
            self.assertEqual(app.player.active_count(), 0)

    def test_simulated_play_ignores_output_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DECKSOUNDPAD_SIMULATE": "1"}):
                app = DeckSoundpadApp(make_paths(Path(tmp)))
            app.update_settings({"play_to_output": True})

            sounds = app.refresh_library()["sounds"]
            play_response = app.play_sound({"sound_id": sounds[0]["id"]})
            playback = app.player.playbacks[play_response["playback_id"]]
            self.assertFalse(app.settings.play_to_output)
            self.assertEqual(playback.routes, ["virtual_mic"])

    def test_simulated_diagnostics_are_marked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DECKSOUNDPAD_SIMULATE": "1"}):
                app = DeckSoundpadApp(make_paths(Path(tmp)))

            diagnostics = app.diagnostics()
            self.assertTrue(diagnostics["simulation"])


if __name__ == "__main__":
    unittest.main()
