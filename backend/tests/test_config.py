from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.config import Settings, load_config, patch_settings, save_config
from decksoundpad.paths import AppPaths, ensure_app_dirs


class ConfigTests(unittest.TestCase):
    def paths(self, root: Path) -> AppPaths:
        plugin = root / "plugin"
        (plugin / "defaults").mkdir(parents=True)
        (plugin / "defaults" / "config.default.json").write_text(
            json.dumps(
                {
                    "library_dirs": ["~/Music/DeckSoundpad"],
                    "web_port": 8787,
                    "master_volume": 1.0,
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

    def test_config_load_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.paths(Path(tmp))
            settings = load_config(paths)
            self.assertEqual(settings.web_port, 8787)
            self.assertEqual(settings.library_dirs, ["~/Music/DeckSoundpad"])
            self.assertFalse(settings.auth_enabled)
            self.assertFalse(settings.background_healthcheck_enabled)
            self.assertTrue(paths.config_file.exists())

    def test_config_patch_validation(self) -> None:
        settings = Settings()
        patched = patch_settings(settings, {"master_volume": 1.25})
        self.assertEqual(patched.master_volume, 1.25)
        route_patched = patch_settings(
            settings,
            {
                "mic_passthrough_enabled": False,
                "play_to_output": True,
                "set_default_source": False,
            },
        )
        self.assertTrue(route_patched.mic_passthrough_enabled)
        self.assertFalse(route_patched.play_to_output)
        self.assertTrue(route_patched.set_default_source)
        healthcheck_patched = patch_settings(settings, {"background_healthcheck_enabled": True})
        self.assertTrue(healthcheck_patched.background_healthcheck_enabled)
        with self.assertRaises(ValueError):
            patch_settings(settings, {"master_volume": 2.0})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"unknown": True})

    def test_config_save_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.paths(Path(tmp))
            settings = Settings(web_port=8790)
            save_config(paths, settings)
            self.assertEqual(load_config(paths).web_port, 8790)

    def test_public_log_dir_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.paths(Path(tmp))
            ensure_app_dirs(paths)
            self.assertEqual(
                paths.public_log_dir,
                paths.user_home / "Public" / "DeckSoundpad" / "logs",
            )
            self.assertTrue(paths.public_log_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
