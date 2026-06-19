from __future__ import annotations

import asyncio
import logging
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.config import Settings, patch_settings  # noqa: E402
from decksoundpad.models import AudioStatus, LibraryStatus, PlayerStatus, Status  # noqa: E402
from decksoundpad.paths import AppPaths, ensure_app_dirs  # noqa: E402
from main import (  # noqa: E402
    EXTERNAL_OVERLAY_GRID_COLUMNS,
    Plugin,
    _input_hotkey_monitor_enabled,
    dominant_steam_deck_stick_direction,
    parse_steam_deck_hid_report,
)


class FakePlayer:
    def __init__(self) -> None:
        self.stop_all_called = False

    def stop_all(self) -> None:
        self.stop_all_called = True


class FakeBackendApp:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.player = FakePlayer()
        self.play_payloads: list[dict[str, object]] = []
        self.stop_payloads: list[dict[str, object]] = []
        self.refresh_calls = 0
        self.repair_calls = 0
        self.raise_status = False
        self.sounds: list[dict[str, object]] = [{"id": "sound-1"}]

    def quick_status(self) -> dict[str, object]:
        if self.raise_status:
            raise RuntimeError("status boom")
        status = Status(
            backend_running=True,
            audio=AudioStatus(state="ready"),
            player=PlayerStatus(
                backend="fake",
                pw_play_available=True,
                ffmpeg_available=False,
                mpv_available=False,
                active_playbacks=0,
            ),
            library=LibraryStatus(count=0, last_scan_at=None),
        ).to_dict()
        status["version"] = "test"
        return status

    def list_sounds(self) -> dict[str, object]:
        return {"ok": True, "sounds": self.sounds}

    def play_sound(self, payload: dict[str, object]) -> dict[str, object]:
        self.play_payloads.append(payload)
        return {"ok": True, "playback_id": "pb-1", "sound_id": payload["sound_id"]}

    def stop(self, payload: dict[str, object]) -> dict[str, object]:
        self.stop_payloads.append(payload)
        return {"ok": True}

    def refresh_library(self) -> dict[str, object]:
        self.refresh_calls += 1
        return {"ok": True, "sounds": [{"id": "sound-1"}]}

    def ensure_audio(self) -> dict[str, object]:
        return AudioStatus(last_error="Audio ensure started", state="starting").to_dict()

    def repair_audio(self) -> dict[str, object]:
        self.repair_calls += 1
        return AudioStatus(last_error="Audio repair started", state="repairing").to_dict()

    def settings_payload(self) -> dict[str, object]:
        return self.settings.to_dict()

    def update_settings(self, patch: dict[str, object]) -> dict[str, object]:
        self.settings = patch_settings(self.settings, patch)
        return self.settings.to_dict()

    def tail_logs(self, _lines: int) -> dict[str, object]:
        return {"ok": True, "public_log_dir": "/tmp/logs", "lines": ["backend line"]}

    def diagnostics(self) -> dict[str, object]:
        return {"settings": self.settings.to_dict()}


class DirectPlugin(Plugin):
    def __init__(self, root: Path) -> None:
        self.paths = AppPaths(
            plugin_dir=root / "plugin",
            settings_dir=root / "settings",
            runtime_dir=root / "runtime",
            log_dir=root / "logs",
            user_home=root / "home",
        )
        (self.paths.plugin_dir / "defaults").mkdir(parents=True)
        (self.paths.plugin_dir / "defaults" / "config.default.json").write_text("{}", encoding="utf-8")
        ensure_app_dirs(self.paths)
        self.settings = Settings()
        self.logger = logging.getLogger("test")
        self._bridge_errors: list[str] = []
        self._backend_lock = threading.RLock()
        self._backend_start_thread = None
        self._healthcheck_stop = None
        self._hotkey_stop = threading.Event()
        self._hotkey_thread = None
        self._hidraw_stop = threading.Event()
        self._hidraw_thread = None
        self._external_overlay_lock = threading.RLock()
        self._external_overlay_process = None
        self._external_overlay_visible = False
        self._external_overlay_sounds: list[dict[str, object]] = []
        self._external_overlay_page = 0
        self._external_overlay_selected_index = 0
        self._external_overlay_message = "Ready"
        self._external_overlay_last_direct_toggle = 0.0
        self._external_overlay_action_stop = threading.Event()
        self._external_overlay_action_thread = None
        self._external_overlay_input_grab_handles = []
        self._external_overlay_input_grab_attempted = False
        self._hidraw_action_last_at: dict[str, float] = {}
        self._hidraw_stick_direction: dict[str, str | None] = {}
        self._hidraw_stick_last_at: dict[str, float] = {}
        self.fake_app = FakeBackendApp(self.settings)
        self.app = self.fake_app

    def _create_backend(self) -> FakeBackendApp:  # type: ignore[override]
        return self.fake_app


class MainAutoStartPlugin(Plugin):
    def __init__(self) -> None:
        self.started = False

    def _create_backend(self) -> FakeBackendApp:  # type: ignore[override]
        return FakeBackendApp(Settings())

    def _request_backend_start_background(self) -> None:
        self.started = True


class MainBridgeTests(unittest.TestCase):
    def test_get_status_uses_in_process_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.get_status())

        self.assertTrue(response["backend_running"])
        self.assertEqual(response["player"]["backend"], "fake")  # type: ignore[index]

    def test_get_status_exception_is_returned_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.raise_status = True
            response = asyncio.run(plugin.get_status())
            logs = asyncio.run(plugin.get_logs_tail())

        self.assertFalse(response["backend_running"])
        self.assertIn("backend unavailable", response["audio"]["last_error"])  # type: ignore[index]
        joined = "\n".join(logs["lines"])
        self.assertIn("status boom", joined)

    def test_play_sound_calls_backend_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.play_sound("sound-1", 0.5))

        self.assertTrue(response["ok"])
        self.assertEqual(plugin.fake_app.play_payloads, [{"sound_id": "sound-1", "volume": 0.5}])

    def test_start_backend_initializes_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.start_backend())
            thread = plugin._backend_start_thread
            if thread is not None:
                thread.join(timeout=1)

        self.assertTrue(response["backend_running"])
        self.assertEqual(plugin.fake_app.repair_calls, 1)
        self.assertEqual(plugin.fake_app.refresh_calls, 1)

    def test_start_backend_does_not_repair_again_after_startup_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            asyncio.run(plugin.start_backend())
            first_thread = plugin._backend_start_thread
            if first_thread is not None:
                first_thread.join(timeout=1)

            response = asyncio.run(plugin.start_backend())

        self.assertTrue(response["backend_running"])
        self.assertEqual(plugin.fake_app.repair_calls, 1)
        self.assertEqual(plugin.fake_app.refresh_calls, 1)

    def test_update_settings_refreshes_cached_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.update_settings({"master_volume": 0.75}))

        self.assertEqual(response["master_volume"], 0.75)
        self.assertEqual(plugin.settings.master_volume, 0.75)

    def test_get_logs_tail_combines_bridge_and_backend_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin._append_bridge_log("bridge line")
            response = asyncio.run(plugin.get_logs_tail())

        joined = "\n".join(response["lines"])
        self.assertIn("bridge line", joined)
        self.assertIn("backend line", joined)

    def test_log_input_event_includes_steam_overlay_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(
                plugin.log_input_event(
                    {
                        "source": "dom.keydown",
                        "phase": "press",
                        "key": "A",
                        "steam_overlay": {
                            "open": True,
                            "quick_access_open": True,
                            "visible_navigation_tree_ids": ["QuickAccess-NA"],
                        },
                    }
                )
            )
            logs = asyncio.run(plugin.get_logs_tail())

        self.assertTrue(response["ok"])
        joined = "\n".join(logs["lines"])
        self.assertIn("source=dom.keydown", joined)
        self.assertIn("steam_overlay_open=true", joined)
        self.assertIn("QuickAccess-NA", joined)

    def test_main_requests_backend_start_on_plugin_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            (plugin_dir / "defaults").mkdir()
            (plugin_dir / "defaults" / "config.default.json").write_text("{}", encoding="utf-8")
            plugin = MainAutoStartPlugin()
            with patch.dict(
                "main.os.environ",
                {
                    "DECKY_USER_HOME": str(root / "home"),
                    "DECKY_PLUGIN_SETTINGS_DIR": str(root / "settings"),
                    "DECKY_PLUGIN_RUNTIME_DIR": str(root / "runtime"),
                    "DECKY_PLUGIN_LOG_DIR": str(root / "logs"),
                },
                clear=False,
            ), patch("main.decky.DECKY_PLUGIN_DIR", str(plugin_dir), create=True):
                asyncio.run(plugin._main())

        self.assertTrue(plugin.started)

    def test_unload_stops_backend_player(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            asyncio.run(plugin._unload())

        self.assertTrue(plugin.fake_app.player.stop_all_called)

    def test_input_hotkey_monitor_is_disabled_without_root(self) -> None:
        with (
            patch.dict("main.os.environ", {}, clear=True),
            patch("main.os.geteuid", return_value=1000),
        ):
            self.assertFalse(_input_hotkey_monitor_enabled())

    def test_input_hotkey_monitor_can_be_enabled_explicitly(self) -> None:
        with (
            patch.dict("main.os.environ", {"DECKSOUNDPAD_ENABLE_INPUT_HOTKEY": "1"}, clear=True),
            patch("main.os.geteuid", return_value=1000),
        ):
            self.assertTrue(_input_hotkey_monitor_enabled())

    def test_bridge_log_is_written_to_public_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin._append_bridge_log("public bridge line")

            content = plugin.paths.public_bridge_log_file.read_text(encoding="utf-8")
            self.assertIn("public bridge line", content)

    def test_external_overlay_vertical_navigation_uses_grid_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin._external_overlay_sounds = [{"id": f"sound-{index}"} for index in range(18)]
            plugin._external_overlay_page = 0
            plugin._external_overlay_selected_index = 1

            plugin._move_external_overlay_selection_vertical(1)
            self.assertEqual(plugin._external_overlay_selected_index, 1 + EXTERNAL_OVERLAY_GRID_COLUMNS)

            plugin._move_external_overlay_selection_vertical(-1)
            self.assertEqual(plugin._external_overlay_selected_index, 1)

            plugin._external_overlay_selected_index = EXTERNAL_OVERLAY_GRID_COLUMNS * 2 + (EXTERNAL_OVERLAY_GRID_COLUMNS - 1)
            plugin._move_external_overlay_selection_vertical(1)
            self.assertEqual(plugin._external_overlay_selected_index, 17)

    def test_play_previous_external_overlay_sound_wraps_across_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = [{"id": f"sound-{index}"} for index in range(23)]

            response = plugin._play_previous_external_overlay_sound_sync()

        self.assertTrue(response["ok"])
        self.assertEqual(plugin.fake_app.play_payloads, [{"sound_id": "sound-22", "volume": None}])
        self.assertEqual(response["page"], 0)
        self.assertEqual(response["selected_index"], 22)

    def test_steam_deck_hid_report_parses_stick_axes(self) -> None:
        data = bytearray(64)
        struct.pack_into("<HBB", data, 0, 0x01, 0x09, 56)
        struct.pack_into("<I", data, 4, 123)
        struct.pack_into("<II", data, 8, 0x80, 0)
        struct.pack_into("<hhhh", data, 48, 16000, -17000, -18000, 500)

        report = parse_steam_deck_hid_report(bytes(data))

        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["buttons_l"], 0x80)
        self.assertEqual(report["left_stick_x"], 16000)
        self.assertEqual(report["left_stick_y"], 17000)
        self.assertEqual(report["right_stick_x"], -18000)
        self.assertEqual(report["right_stick_y"], -500)
        self.assertEqual(dominant_steam_deck_stick_direction(report), "left")


if __name__ == "__main__":
    unittest.main()
