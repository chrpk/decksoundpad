from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.app import DeckSoundpadApp
from decksoundpad.paths import AppPaths
from decksoundpad.simulation import (
    SimulatedAudioRouter,
    SimulatedPlaybackManager,
    simulation_enabled,
)


def make_paths(root: Path) -> AppPaths:
    plugin = root / "plugin"
    bundled = plugin / "defaults" / "sounds" / "sample"
    bundled.mkdir(parents=True)
    (bundled / "ready.wav").write_bytes(b"wav")
    (plugin / "defaults" / "config.default.json").write_text(
        json.dumps(
            {
                "library_dirs": [str(root / "sounds")],
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
            self.assertTrue(status["backend_running"])
            self.assertEqual(status["player"]["backend"], "simulated")
            self.assertTrue(status["audio"]["sink_exists"])
            self.assertTrue(status["audio"]["virtual_mic_exists"])
            self.assertEqual(status["audio"]["selected_real_mic"], "simulated_real_mic")
            self.assertEqual(status["audio"]["default_source"], "simulated_real_mic")
            self.assertFalse(status["audio"]["is_default_source"])

    def test_simulated_play_and_player_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DECKSOUNDPAD_SIMULATE": "1"}):
                app = DeckSoundpadApp(make_paths(Path(tmp)))

            sounds = app.refresh_library()["sounds"]
            self.assertEqual(len(sounds), 1)
            sound_id = sounds[0]["id"]

            play_response = app.play_sound({"sound_id": sound_id, "volume": 0.5})
            self.assertTrue(play_response["ok"])
            self.assertTrue(str(play_response["playback_id"]).startswith("sim_pb_"))
            self.assertIn(play_response["playback_id"], app.player.playbacks)

            app.player.stop_all()
            self.assertEqual(app.player.playbacks, {})


if __name__ == "__main__":
    unittest.main()
