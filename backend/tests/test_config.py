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
            user_home=root / "home",
        )

    def test_config_load_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.paths(Path(tmp))
            settings = load_config(paths)
            self.assertEqual(settings.library_dirs, ["~/Music/DeckSoundpad"])
            self.assertEqual(settings.max_playback_seconds, 30.0)
            self.assertFalse(settings.background_healthcheck_enabled)
            self.assertEqual(settings.overlay_hotkey_button, "l5")
            self.assertEqual(settings.overlay_input_device, "auto")
            self.assertTrue(paths.config_file.exists())

    def test_config_patch_validation(self) -> None:
        settings = Settings()
        patched = patch_settings(settings, {"master_volume": 1.25})
        self.assertEqual(patched.master_volume, 1.25)
        mic_volume_patched = patch_settings(settings, {"mic_passthrough_volume": 1.5})
        self.assertEqual(mic_volume_patched.mic_passthrough_volume, 1.5)
        route_patched = patch_settings(settings, {"mic_passthrough_enabled": False})
        self.assertFalse(route_patched.mic_passthrough_enabled)
        healthcheck_patched = patch_settings(
            settings, {"background_healthcheck_enabled": True}
        )
        self.assertTrue(healthcheck_patched.background_healthcheck_enabled)
        time_patched = patch_settings(settings, {"max_playback_seconds": 45})
        self.assertEqual(time_patched.max_playback_seconds, 45.0)
        for button in ("l4", "l5", "r4", "r5"):
            with self.subTest(button=button):
                hotkey_patched = patch_settings(
                    settings, {"overlay_hotkey_button": button}
                )
                self.assertEqual(hotkey_patched.overlay_hotkey_button, button)
        auto_device = patch_settings(settings, {"overlay_input_device": "auto"})
        self.assertEqual(auto_device.overlay_input_device, "auto")
        selected_device = patch_settings(
            settings,
            {"overlay_input_device": "evdev:0123456789abcdef"},
        )
        self.assertEqual(selected_device.overlay_input_device, "evdev:0123456789abcdef")
        with self.assertRaises(ValueError):
            patch_settings(settings, {"master_volume": 2.0})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"mic_passthrough_volume": 1.6})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"mic_passthrough_volume": -0.1})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"overlay_input_device": "/dev/input/event4"})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"overlay_hotkey_button": "menu"})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"max_playback_seconds": 0})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"unknown": True})
        with self.assertRaises(ValueError):
            patch_settings(settings, {"overlay_hotkey_button": "a"})

    def test_legacy_single_mode_config_migrates_to_overlap_with_time_limit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.paths(Path(tmp))
            ensure_app_dirs(paths)
            paths.config_file.write_text(
                json.dumps({"overlap_mode": "single", "max_concurrent_sounds": 6}),
                encoding="utf-8",
            )

            settings = load_config(paths)

            self.assertEqual(settings.overlap_mode, "overlap")
            self.assertEqual(settings.max_playback_seconds, 30.0)
            saved = json.loads(paths.config_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["overlap_mode"], "overlap")
            self.assertEqual(saved["max_playback_seconds"], 30.0)

    def test_config_save_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.paths(Path(tmp))
            selector = "evdev:0123456789abcdef"
            settings = Settings(master_volume=0.9, overlay_input_device=selector)
            save_config(paths, settings)
            loaded = load_config(paths)
            self.assertEqual(loaded.master_volume, 0.9)
            self.assertEqual(loaded.overlay_input_device, selector)

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
