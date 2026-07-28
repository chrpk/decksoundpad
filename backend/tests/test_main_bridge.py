from __future__ import annotations

import asyncio
import logging
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.config import Settings, patch_settings  # noqa: E402
from decksoundpad.models import AudioStatus, LibraryStatus, PlayerStatus, Status  # noqa: E402
from decksoundpad.paths import AppPaths, ensure_app_dirs  # noqa: E402
import main as main_bridge  # noqa: E402
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
            ),
            library=LibraryStatus(count=0),
        ).to_dict()
        status["version"] = "test"
        return status

    def list_sounds(self) -> dict[str, object]:
        return {"ok": True, "sounds": self.sounds}

    def play_sound(self, payload: dict[str, object]) -> dict[str, object]:
        self.play_payloads.append(payload)
        return {"ok": True, "playback_id": "pb-1", "sound_id": payload["sound_id"]}

    def refresh_library(self) -> dict[str, object]:
        self.refresh_calls += 1
        return {"ok": True, "sounds": [{"id": "sound-1"}]}

    def repair_audio(self) -> dict[str, object]:
        self.repair_calls += 1
        return AudioStatus(last_error="DeckSoundpad restart started", state="repairing").to_dict()

    def settings_payload(self) -> dict[str, object]:
        return self.settings.to_dict()

    def update_settings(self, patch: dict[str, object]) -> dict[str, object]:
        self.settings = patch_settings(self.settings, patch)
        return self.settings.to_dict()


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
        self._input_restart_thread = None
        self._input_restart_requested = threading.Event()
        self._input_restart_request_lock = threading.Lock()
        self._input_monitor_lock = threading.RLock()
        self._input_restarts_disabled = False
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
        self._external_overlay_evdev_stop = threading.Event()
        self._external_overlay_evdev_thread = None
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

        self.assertFalse(response["backend_running"])
        self.assertIn("backend unavailable", response["audio"]["last_error"])  # type: ignore[index]
        joined = "\n".join(plugin._bridge_errors)
        self.assertIn("status boom", joined)

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

    def test_update_settings_refreshes_overlay_hotkey_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.update_settings({"overlay_hotkey_button": "r4"}))

        self.assertEqual(response["overlay_hotkey_button"], "r4")
        self.assertEqual(plugin.settings.overlay_hotkey_button, "r4")

    def test_update_settings_refreshes_overlay_input_device(self) -> None:
        selector = "evdev:0123456789abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with patch.object(plugin, "_request_input_monitor_restart") as restart:
                response = asyncio.run(plugin.update_settings({"overlay_input_device": selector}))

        self.assertEqual(response["overlay_input_device"], selector)
        self.assertEqual(plugin.settings.overlay_input_device, selector)
        restart.assert_called_once_with()

    def test_get_input_devices_returns_auto_and_discovered_controllers(self) -> None:
        discovered = [
            {
                "id": "evdev:0123456789abcdef",
                "name": "Xbox Wireless Controller",
                "path": "/dev/input/event7",
                "label": "Xbox Wireless Controller (event7)",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with patch("main.discover_overlay_input_devices", return_value=discovered):
                response = asyncio.run(plugin.get_input_devices())

        self.assertEqual(response["devices"][0]["id"], "auto")
        self.assertEqual(response["devices"][1:], discovered)

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
                try:
                    asyncio.run(plugin._main())
                finally:
                    asyncio.run(plugin._unload())

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

    def test_hidraw_monitor_does_not_start_without_root_input_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch.dict("main.os.environ", {}, clear=True),
                patch("main.os.geteuid", return_value=1000),
            ):
                plugin._start_hidraw_monitor()

        self.assertIsNone(plugin._hidraw_thread)
        self.assertIn("no root hidraw access", "\n".join(plugin._bridge_errors))

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

            response = plugin._play_previous_external_overlay_sound()

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

    def test_overlay_hotkey_button_mappings_cover_all_rear_buttons(self) -> None:
        self.assertEqual(
            main_bridge.STEAM_DECK_REAR_BUTTON_MASKS,
            {
                "l4": 1 << 41,
                "l5": 1 << 15,
                "r4": 1 << 42,
                "r5": 1 << 16,
            },
        )
        self.assertEqual(main_bridge.overlay_hotkey_event_codes("l4"), frozenset({0x224}))
        self.assertEqual(main_bridge.overlay_hotkey_event_codes("l5"), frozenset({0x226}))
        self.assertEqual(main_bridge.overlay_hotkey_event_codes("r4"), frozenset({0x225}))
        self.assertEqual(main_bridge.overlay_hotkey_event_codes("r5"), frozenset({0x227}))
        self.assertEqual(
            main_bridge.EVDEV_OVERLAY_ACTIONS,
            {
                0x130: "play",
                0x220: "up",
                0x221: "down",
                0x222: "left",
                0x223: "right",
                0x136: "page_prev",
                0x137: "page_next",
            },
        )

    def test_automatic_l5_preserves_legacy_event_code_aliases(self) -> None:
        codes = main_bridge.overlay_hotkey_event_codes("l5", include_legacy_l5=True)

        self.assertIn(0x138, codes)  # BTN_TL2
        self.assertIn(0x224, codes)  # BTN_GRIPL
        self.assertIn(0x226, codes)  # BTN_GRIPL2
        self.assertIn(0x2C0, codes)  # BTN_TRIGGER_HAPPY1
        self.assertIn(0x2E7, codes)  # BTN_TRIGGER_HAPPY40

    def test_input_device_relevance_requires_controller_and_hotkey_capabilities(self) -> None:
        capabilities = frozenset({0x130, 0x226})

        self.assertTrue(
            main_bridge.is_overlay_input_device_relevant(
                "Xbox Elite Wireless Controller",
                capabilities,
            )
        )
        self.assertFalse(
            main_bridge.is_overlay_input_device_relevant(
                "Gaming Keyboard",
                capabilities,
            )
        )
        self.assertFalse(
            main_bridge.is_overlay_input_device_relevant(
                "Pretend Controller",
                frozenset({0x130}),
            )
        )

    def test_input_device_selector_is_stable_across_event_path_changes(self) -> None:
        first = main_bridge.make_input_device_selector(
            "Xbox Wireless Controller",
            "usb-0000:00:14.0-2/input0",
            "controller-serial",
            "/dev/input/event4",
        )
        second = main_bridge.make_input_device_selector(
            "Xbox Wireless Controller",
            "usb-0000:00:14.0-2/input0",
            "controller-serial",
            "/dev/input/event9",
        )
        other = main_bridge.make_input_device_selector(
            "Xbox Wireless Controller",
            "usb-0000:00:14.0-3/input0",
            "controller-serial",
            "/dev/input/event4",
        )

        self.assertEqual(first, second)
        self.assertRegex(first or "", r"^evdev:[0-9a-f]{16}$")
        self.assertNotEqual(first, other)

    def test_input_device_without_stable_kernel_identity_is_not_selectable(self) -> None:
        selector = main_bridge.make_input_device_selector(
            "Generic Controller",
            "",
            "",
            "/dev/input/event4",
        )

        self.assertIsNone(selector)

    def test_filter_overlay_input_devices_honors_explicit_selection(self) -> None:
        first = {"id": "evdev:0000000000000001", "name": "First", "path": "/dev/input/event4"}
        second = {"id": "evdev:0000000000000002", "name": "Second", "path": "/dev/input/event7"}
        devices = [first, second]

        self.assertEqual(main_bridge.filter_overlay_input_devices(devices, "auto"), devices)
        self.assertEqual(
            main_bridge.filter_overlay_input_devices(devices, second["id"]),
            [second],
        )
        self.assertEqual(
            main_bridge.filter_overlay_input_devices(devices, "evdev:ffffffffffffffff"),
            [],
        )

    def test_duplicate_event_nodes_for_one_controller_are_collapsed(self) -> None:
        devices = [
            {
                "id": "evdev:0000000000000001",
                "name": "Controller",
                "path": "/dev/input/event4",
                "label": "Controller (event4)",
            },
            {
                "id": "evdev:0000000000000001",
                "name": "Controller",
                "path": "/dev/input/event5",
                "label": "Controller (event5)",
            },
        ]

        self.assertEqual(
            main_bridge.deduplicate_overlay_input_devices(devices),
            [devices[0]],
        )

    def test_unavailable_explicit_input_device_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.settings = Settings(
                overlay_input_device="evdev:ffffffffffffffff"
            )
            with patch(
                "main.discover_overlay_input_devices",
                return_value=[
                    {
                        "id": "evdev:0000000000000001",
                        "name": "Other Controller",
                        "path": "/dev/input/event4",
                        "label": "Other Controller (event4)",
                    }
                ],
            ):
                handles = plugin._open_input_event_devices()

        self.assertEqual(handles, [])

    def test_automatic_mode_reads_evdev_devices_after_grab(self) -> None:
        device = {
            "id": "evdev:0000000000000001",
            "name": "Steam Deck",
            "path": "/dev/input/event4",
            "label": "Steam Deck (event4)",
        }
        fake_handle = MagicMock()
        fake_handle.fileno.return_value = 42
        fake_fcntl = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch("main.discover_overlay_input_devices", return_value=[device]),
                patch.object(main_bridge.Path, "open", return_value=fake_handle),
                patch.object(main_bridge, "fcntl", fake_fcntl),
                patch.object(main_bridge.os, "set_blocking"),
                patch.object(plugin, "_start_external_overlay_evdev_reader") as start_reader,
            ):
                plugin._grab_external_overlay_input_devices()
                start_reader.assert_called_once_with()
                plugin._release_external_overlay_input_grab()

    def test_input_restart_coordinator_does_not_drop_a_pending_restart(self) -> None:
        first_started = threading.Event()
        allow_first_to_finish = threading.Event()
        calls: list[int] = []

        def restart() -> None:
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                first_started.set()
                allow_first_to_finish.wait(timeout=1.0)

        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with patch.object(plugin, "_restart_input_monitors", side_effect=restart):
                plugin._request_input_monitor_restart()
                worker = plugin._input_restart_thread
                self.assertIsNotNone(worker)
                self.assertTrue(first_started.wait(timeout=1.0))
                plugin._request_input_monitor_restart()
                allow_first_to_finish.set()
                assert worker is not None
                worker.join(timeout=1.0)

        self.assertEqual(calls, [1, 2])

    def test_overlay_action_is_deduplicated_across_hidraw_and_evdev(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch.object(
                    plugin,
                    "_handle_external_overlay_input",
                    return_value={"visible": True},
                ) as handle_action,
                patch("main.time.monotonic", side_effect=[10.0, 10.1]),
            ):
                first = plugin._handle_debounced_overlay_action(
                    "right",
                    "hidraw-input",
                    "/dev/hidraw0",
                )
                duplicate = plugin._handle_debounced_overlay_action(
                    "right",
                    "evdev-grab",
                    "/dev/input/event4",
                )

        self.assertTrue(first)
        self.assertFalse(duplicate)
        handle_action.assert_called_once_with("right")

    def test_stopped_evdev_reader_cannot_dispatch_a_stale_press(self) -> None:
        stopped = threading.Event()
        stopped.set()
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with patch.object(plugin, "_handle_overlay_direct_hotkey") as toggle:
                plugin._handle_external_overlay_evdev_press(
                    0x226,
                    "/dev/input/event4",
                    stopped,
                )

        toggle.assert_not_called()

    def test_selected_evdev_press_routes_overlay_hotkey_and_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.settings = Settings(overlay_hotkey_button="r4")
            with (
                patch.object(plugin, "_handle_overlay_direct_hotkey") as hotkey,
                patch.object(plugin, "_handle_external_overlay_input") as action,
            ):
                plugin._handle_external_overlay_evdev_press(0x225, "/dev/input/event7")
                plugin._handle_external_overlay_evdev_press(0x223, "/dev/input/event7")

        hotkey.assert_called_once_with("evdev-grab")
        action.assert_called_once_with("right")

    def test_external_overlay_state_uses_configured_hotkey_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.settings = Settings(overlay_hotkey_button="r4")
            plugin._external_overlay_visible = True
            commands: list[dict[str, object]] = []

            with (
                patch.object(plugin, "_send_external_overlay_command", commands.append),
                patch.object(plugin, "_sync_external_overlay_input_grab"),
            ):
                plugin._send_external_overlay_state()

        self.assertEqual(commands[0]["overlay_hotkey_button"], "R4")


if __name__ == "__main__":
    unittest.main()
