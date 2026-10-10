from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.config import Settings, patch_settings  # noqa: E402
from decksoundpad.input_devices import (  # noqa: E402
    BTN_GRIPL2,
    EV_KEY,
    INPUT_EVENT_STRUCT,
    STEAM_DECK_LBUTTON_A,
    STEAM_DECK_REAR_BUTTON_MASKS,
)
from decksoundpad.models import AudioStatus, LibraryStatus, PlayerStatus, Status  # noqa: E402
from decksoundpad.overlay_layout import SOUNDS_PER_PAGE  # noqa: E402
from decksoundpad.overlay_model import load_recent_ids, save_recent_ids  # noqa: E402
from decksoundpad.paths import AppPaths, ensure_app_dirs  # noqa: E402

from main import (  # noqa: E402
    Plugin,
    _input_hotkey_monitor_enabled,
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
        self.test_sound_calls = 0
        self.repair_calls = 0
        self.close_calls = 0
        self.raise_status = False
        self.audio_status = AudioStatus(state="ready")
        self.sounds: list[dict[str, object]] = [{"id": "sound-1"}]
        self.playing: set[str] = set()
        self.play_error: str | None = None
        self.stop_all_sounds_calls = 0

    def quick_status(self) -> dict[str, object]:
        if self.raise_status:
            raise RuntimeError("status boom")
        status = Status(
            backend_running=True,
            audio=self.audio_status,
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
        if self.play_error is not None:
            return {"ok": False, "error": self.play_error}
        self.playing.add(str(payload["sound_id"]))
        return {"ok": True, "playback_id": "pb-1", "sound_id": payload["sound_id"]}

    def playing_sound_ids(self) -> frozenset[str]:
        return frozenset(self.playing)

    def stop_all_sounds(self) -> dict[str, object]:
        self.stop_all_sounds_calls += 1
        self.playing.clear()
        return {"ok": True}

    def play_test_sound(self) -> dict[str, object]:
        self.test_sound_calls += 1
        return {"ok": True, "playback_id": "pb-beep", "sound_id": "test_beep"}

    def refresh_library(self) -> dict[str, object]:
        self.refresh_calls += 1
        return {"ok": True, "sounds": [{"id": "sound-1"}]}

    def repair_audio(
        self,
        *,
        before_restart: object = None,
        after_restart: object = None,
    ) -> dict[str, object]:
        self.repair_calls += 1
        if callable(before_restart):
            before_restart()
        if callable(after_restart):
            after_restart()
        return AudioStatus(
            last_error="DeckSoundpad restart started", state="repairing"
        ).to_dict()

    def close(self) -> None:
        self.close_calls += 1
        self.player.stop_all()

    def settings_payload(self) -> dict[str, object]:
        return self.settings.to_dict()

    def update_settings(self, patch: dict[str, object]) -> dict[str, object]:
        self.settings = patch_settings(self.settings, patch)
        return self.settings.to_dict()

    def set_library_folder(self, folder: str) -> dict[str, object]:
        self.settings = patch_settings(self.settings, {"library_dirs": [folder]})
        return {"ok": True, "settings": self.settings.to_dict(), "sounds": self.sounds}


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
        (self.paths.plugin_dir / "defaults" / "config.default.json").write_text(
            "{}", encoding="utf-8"
        )
        ensure_app_dirs(self.paths)
        self.settings = Settings()
        self.logger = logging.getLogger("test")
        self._init_bridge_state()
        self.fake_app = FakeBackendApp(self.settings)
        self.app = self.fake_app
        self.bridge_teardown_calls = 0
        self.bridge_reinitialization_calls = 0

    def _create_backend(self) -> FakeBackendApp:  # type: ignore[override]
        return self.fake_app

    def _prepare_bridge_runtime_restart(self) -> None:
        self.bridge_teardown_calls += 1

    def _finish_bridge_runtime_restart(self) -> None:
        self.bridge_reinitialization_calls += 1
        self.settings = self.fake_app.settings


def sound_items(
    count: int, category: str = "uncategorized", start: int = 0
) -> list[dict[str, object]]:
    return [
        {
            "id": f"sound-{index}",
            "display_name": f"Sound {index}",
            "relative_path": f"sound-{index}.wav",
            "category": category,
        }
        for index in range(start, start + count)
    ]


@contextmanager
def captured_overlay(plugin: DirectPlugin) -> Iterator[list[dict[str, object]]]:
    """Record overlay commands instead of starting the GTK overlay process."""

    commands: list[dict[str, object]] = []
    with (
        patch.object(
            plugin,
            "_send_external_overlay_command",
            side_effect=lambda command, **_kwargs: commands.append(command),
        ),
        patch.object(plugin, "_sync_external_overlay_input_grab"),
    ):
        try:
            yield commands
        finally:
            plugin._external_overlay_playing_stop.set()
            thread = plugin._external_overlay_playing_thread
            if thread is not None:
                thread.join(timeout=2.0)


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

    def test_repair_audio_restarts_backend_and_bridge_lifecycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.repair_audio())

        self.assertTrue(response["backend_running"])
        self.assertEqual(plugin.fake_app.repair_calls, 1)
        self.assertEqual(plugin.bridge_teardown_calls, 1)
        self.assertEqual(plugin.bridge_reinitialization_calls, 1)

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

    def test_play_test_sound_calls_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.play_test_sound())

        self.assertTrue(response["ok"])
        self.assertEqual(plugin.fake_app.test_sound_calls, 1)

    def test_update_settings_refreshes_cached_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.update_settings({"master_volume": 0.75}))

        self.assertEqual(response["master_volume"], 0.75)
        self.assertEqual(plugin.settings.master_volume, 0.75)

    def test_set_library_folder_refreshes_cached_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(plugin.set_library_folder("/media/sounds"))

        self.assertTrue(response["ok"])
        self.assertEqual(response["sounds"], [{"id": "sound-1"}])
        self.assertEqual(plugin.settings.library_dirs, ["/media/sounds"])

    def test_set_library_folder_returns_fallback_when_backend_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with patch.object(
                plugin.fake_app, "set_library_folder", side_effect=RuntimeError("boom")
            ):
                response = asyncio.run(plugin.set_library_folder("/media/sounds"))

        self.assertFalse(response["ok"])
        self.assertEqual(response["sounds"], [])
        self.assertEqual(response["settings"]["library_dirs"], Settings().library_dirs)  # type: ignore[index]

    def test_update_settings_refreshes_overlay_hotkey_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            response = asyncio.run(
                plugin.update_settings({"overlay_hotkey_button": "r4"})
            )

        self.assertEqual(response["overlay_hotkey_button"], "r4")
        self.assertEqual(plugin.settings.overlay_hotkey_button, "r4")

    def test_update_settings_refreshes_overlay_input_device(self) -> None:
        selector = "evdev:0123456789abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with patch.object(plugin, "_request_input_monitor_restart") as restart:
                response = asyncio.run(
                    plugin.update_settings({"overlay_input_device": selector})
                )

        self.assertEqual(response["overlay_input_device"], selector)
        self.assertEqual(plugin.settings.overlay_input_device, selector)
        restart.assert_called_once_with()

    def test_full_runtime_restart_reinitializes_bridge_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin._bridge_errors = ["stale error"]
            plugin._external_overlay_visible = True
            plugin._external_overlay_sounds = [{"id": "old"}]
            plugin._external_overlay_tab_index = 2
            plugin._external_overlay_cursor = 12
            plugin._external_overlay_toast = {"text": "stale", "tone": "play"}
            plugin._input_action_last_at["old"] = 1.0
            plugin._hidraw_stick_state["old"] = ("left", 1.0)
            plugin._healthcheck_stop = threading.Event()
            with (
                patch.object(
                    plugin, "_stop_input_monitor_restart_coordinator"
                ) as stop_coordinator,
                patch.object(plugin, "_stop_external_overlay") as stop_overlay,
                patch.object(plugin, "_stop_hotkey_monitor") as stop_hotkey,
                patch.object(plugin, "_stop_hidraw_monitor") as stop_hidraw,
                patch.object(
                    plugin, "_stop_external_overlay_action_server"
                ) as stop_actions,
            ):
                Plugin._prepare_bridge_runtime_restart(plugin)

            stop_coordinator.assert_called_once_with()
            stop_overlay.assert_called_once_with()
            stop_hotkey.assert_called_once_with()
            stop_hidraw.assert_called_once_with()
            stop_actions.assert_called_once_with()
            self.assertIsNone(plugin._healthcheck_stop)
            self.assertFalse(plugin._external_overlay_visible)
            self.assertEqual(plugin._external_overlay_sounds, [])
            self.assertEqual(plugin._external_overlay_tab_index, 0)
            self.assertEqual(plugin._external_overlay_cursor, 0)
            self.assertIsNone(plugin._external_overlay_toast)
            self.assertNotIn("stale error", plugin._bridge_errors)
            self.assertTrue(
                any(
                    "bridge teardown finished" in entry
                    for entry in plugin._bridge_errors
                )
            )
            self.assertEqual(plugin._input_action_last_at, {})
            self.assertEqual(plugin._hidraw_stick_state, {})

            plugin._input_restarts_disabled = True
            with (
                patch.object(plugin, "_start_healthcheck") as start_healthcheck,
                patch.object(
                    plugin, "_start_external_overlay_action_server"
                ) as start_actions,
                patch.object(plugin, "_start_hotkey_monitor") as start_hotkey,
                patch.object(plugin, "_start_hidraw_monitor") as start_hidraw,
            ):
                Plugin._finish_bridge_runtime_restart(plugin)

            self.assertFalse(plugin._input_restarts_disabled)
            start_healthcheck.assert_called_once_with()
            start_actions.assert_called_once_with()
            start_hotkey.assert_called_once_with()
            start_hidraw.assert_called_once_with()

    def test_bridge_reinitialization_does_not_resurrect_unloaded_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin._unloading = True
            plugin._input_restarts_disabled = True
            with (
                patch.object(plugin, "_start_healthcheck") as start_healthcheck,
                patch.object(
                    plugin, "_start_external_overlay_action_server"
                ) as start_actions,
                patch.object(plugin, "_start_hotkey_monitor") as start_hotkey,
                patch.object(plugin, "_start_hidraw_monitor") as start_hidraw,
            ):
                Plugin._finish_bridge_runtime_restart(plugin)

        start_healthcheck.assert_not_called()
        start_actions.assert_not_called()
        start_hotkey.assert_not_called()
        start_hidraw.assert_not_called()
        self.assertTrue(plugin._input_restarts_disabled)
        self.assertTrue(
            any("skipped during unload" in entry for entry in plugin._bridge_errors)
        )

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
            (plugin_dir / "defaults" / "config.default.json").write_text(
                "{}", encoding="utf-8"
            )
            plugin = MainAutoStartPlugin()
            with (
                patch.dict(
                    "main.os.environ",
                    {
                        "DECKY_USER_HOME": str(root / "home"),
                        "DECKY_PLUGIN_SETTINGS_DIR": str(root / "settings"),
                        "DECKY_PLUGIN_RUNTIME_DIR": str(root / "runtime"),
                        "DECKY_PLUGIN_LOG_DIR": str(root / "logs"),
                    },
                    clear=False,
                ),
                patch("main.decky.DECKY_PLUGIN_DIR", str(plugin_dir), create=True),
            ):
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

    def test_input_hotkey_monitor_enabled_for_normal_user(self) -> None:
        with (
            patch.dict("main.os.environ", {}, clear=True),
            patch("main.os.geteuid", return_value=1000),
        ):
            self.assertTrue(_input_hotkey_monitor_enabled())

    def test_input_hotkey_monitor_can_be_disabled_explicitly(self) -> None:
        with (
            patch.dict(
                "main.os.environ", {"DECKSOUNDPAD_ENABLE_INPUT_HOTKEY": "0"}, clear=True
            ),
            patch("main.os.geteuid", return_value=1000),
        ):
            self.assertFalse(_input_hotkey_monitor_enabled())

    def test_input_hotkey_monitor_can_be_enabled_explicitly(self) -> None:
        with (
            patch.dict(
                "main.os.environ", {"DECKSOUNDPAD_ENABLE_INPUT_HOTKEY": "1"}, clear=True
            ),
            patch("main.os.geteuid", return_value=1000),
        ):
            self.assertTrue(_input_hotkey_monitor_enabled())

    def test_hidraw_monitor_starts_without_root_input_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch.dict("main.os.environ", {}, clear=True),
                patch("main.os.geteuid", return_value=1000),
                patch.object(plugin, "_open_hidraw_devices", return_value=[]),
            ):
                plugin._start_hidraw_monitor()
                try:
                    self.assertIsNotNone(plugin._hidraw_thread)
                finally:
                    plugin._stop_hidraw_monitor()

        self.assertIsNone(plugin._hidraw_thread)

    def test_bridge_log_is_written_to_public_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin._append_bridge_log("public bridge line")

            content = plugin.paths.public_bridge_log_file.read_text(encoding="utf-8")
            self.assertIn("public bridge line", content)

    def test_bridge_log_keeps_one_previous_file_when_it_grows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            log_file = plugin.paths.public_bridge_log_file
            with patch("main.PUBLIC_LOG_MAX_BYTES", 300):
                for index in range(30):
                    plugin._append_bridge_log(f"line {index:02d} " + "x" * 40)

            rotated = log_file.with_name(f"{log_file.name}.1")
            self.assertTrue(rotated.exists())
            self.assertLessEqual(log_file.stat().st_size, 300 + 80)
            self.assertIn("line 29", log_file.read_text(encoding="utf-8"))

    def test_retried_input_device_problems_are_logged_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.settings = Settings(
                overlay_input_device="evdev:ffffffffffffffff"
            )
            with (
                patch("main.discover_overlay_input_devices", return_value=[]),
                patch.object(plugin, "_start_hotkey_monitor"),
                patch.object(plugin, "_start_hidraw_monitor"),
            ):
                for _retry in range(3):
                    plugin._open_input_event_devices()
                first = "\n".join(plugin._bridge_errors)
                plugin._restart_input_monitors()
                plugin._open_input_event_devices()

        self.assertEqual(first.count("Configured overlay input device unavailable"), 1)
        # A monitor restart reports the problem again.
        self.assertEqual(
            "\n".join(plugin._bridge_errors).count(
                "Configured overlay input device unavailable"
            ),
            2,
        )

    def test_overlay_opens_on_recent_and_reports_mic_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(3)
            plugin.fake_app.audio_status = AudioStatus(
                state="ready",
                pactl_available=True,
                pipewire_available=True,
                sink_exists=True,
                virtual_mic_exists=True,
                loopback_exists=True,
            )
            save_recent_ids(plugin.paths.overlay_recent_file, ["sound-2", "deleted"])
            with captured_overlay(plugin) as commands:
                response = plugin._toggle_external_overlay({"source": "frontend"})

        state = commands[-1]
        self.assertTrue(response["visible"])
        self.assertEqual(
            [tab["label"] for tab in state["tabs"]], ["Recent", "All sounds"]
        )
        self.assertEqual(state["tab_index"], 0)
        self.assertEqual([sound["id"] for sound in state["sounds"]], ["sound-2"])
        self.assertEqual(state["mic"], {"tone": "ok", "label": "Mic ready"})
        self.assertEqual(state["message"], "")
        self.assertNotIn("toast", state)

    def test_a_plays_closes_with_toast_and_remembers_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(3)
            with captured_overlay(plugin) as commands:
                plugin._toggle_external_overlay({"source": "frontend"})
                plugin._handle_external_overlay_input("right")
                response = plugin._handle_external_overlay_input("play")
            recent = load_recent_ids(plugin.paths.overlay_recent_file)

        self.assertFalse(response["visible"])
        self.assertEqual(
            plugin.fake_app.play_payloads, [{"sound_id": "sound-1", "volume": None}]
        )
        self.assertEqual(commands[-1]["toast"], {"text": "Sound 1", "tone": "play"})
        self.assertFalse(commands[-1]["visible"])
        self.assertEqual(recent, ["sound-1"])

    def test_x_plays_and_stays_open_until_the_sound_ends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(3)
            with captured_overlay(plugin) as commands:
                plugin._toggle_external_overlay({"source": "frontend"})
                response = plugin._handle_external_overlay_input("play_stay")
                playing_state = dict(commands[-1])

                # The sound ends; the playing watch clears the tile marker.
                plugin.fake_app.playing.clear()
                deadline = time.monotonic() + 3.0
                while commands[-1]["playing_ids"] and time.monotonic() < deadline:
                    time.sleep(0.05)
                final_state = commands[-1]

        self.assertTrue(response["visible"])
        self.assertTrue(playing_state["visible"])
        self.assertNotIn("toast", playing_state)
        self.assertEqual(playing_state["playing_ids"], ["sound-0"])
        self.assertEqual(playing_state["message"], "Playing Sound 0")
        self.assertEqual(final_state["playing_ids"], [])
        self.assertTrue(final_state["visible"])

    def test_y_stops_all_sounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(3)
            plugin.fake_app.playing = {"sound-0"}
            with captured_overlay(plugin) as commands:
                plugin._toggle_external_overlay({"source": "frontend"})
                self.assertEqual(commands[-1]["playing_ids"], ["sound-0"])
                plugin._handle_external_overlay_input("stop")

        self.assertEqual(plugin.fake_app.stop_all_sounds_calls, 1)
        self.assertEqual(commands[-1]["playing_ids"], [])
        self.assertEqual(commands[-1]["message"], "Stopped all sounds")
        self.assertTrue(commands[-1]["visible"])

    def test_b_closes_without_playing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(3)
            with captured_overlay(plugin) as commands:
                plugin._toggle_external_overlay({"source": "frontend"})
                response = plugin._handle_external_overlay_input("hide")

        self.assertFalse(response["visible"])
        self.assertEqual(plugin.fake_app.play_payloads, [])
        self.assertNotIn("toast", commands[-1])

    def test_failed_play_stays_open_with_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(2)
            plugin.fake_app.play_error = "maximum concurrent sounds reached"
            with captured_overlay(plugin) as commands:
                plugin._toggle_external_overlay({"source": "frontend"})
                response = plugin._handle_external_overlay_input("play")
            recent = load_recent_ids(plugin.paths.overlay_recent_file)

        self.assertTrue(response["visible"])
        self.assertEqual(commands[-1]["message_tone"], "error")
        self.assertIn("maximum concurrent sounds reached", commands[-1]["message"])
        self.assertEqual(recent, [])

    def test_shoulder_buttons_flip_pages_across_folder_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(40, "memes") + sound_items(
                2, "music", start=40
            )
            with captured_overlay(plugin) as commands:
                plugin._toggle_external_overlay({"source": "frontend"})
                plugin._handle_external_overlay_input("right")
                plugin._handle_external_overlay_input("right")
                plugin._handle_external_overlay_input("right")
                plugin._handle_external_overlay_input("page_next")
                second_page = dict(commands[-1])
                plugin._handle_external_overlay_input("page_next")
                next_tab = dict(commands[-1])
                plugin._handle_external_overlay_input("page_prev")
                back = commands[-1]

        self.assertEqual(
            [tab["label"] for tab in second_page["tabs"]], ["memes", "music"]
        )
        self.assertEqual((second_page["tab_index"], second_page["page"]), (0, 1))
        self.assertEqual(second_page["selected_index"], 3)
        self.assertEqual(second_page["sounds"][3]["id"], f"sound-{SOUNDS_PER_PAGE + 3}")
        self.assertEqual(
            (next_tab["tab_index"], next_tab["page"], next_tab["selected_index"]),
            (1, 0, 1),
        )
        self.assertEqual((back["tab_index"], back["page"]), (0, 1))

    def test_touch_selects_page_relative_tiles_and_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(40, "memes") + sound_items(
                2, "music", start=40
            )
            with captured_overlay(plugin) as commands:
                plugin._toggle_external_overlay({"source": "frontend"})
                plugin._handle_external_overlay_action({"type": "tab", "index": 1})
                tab_state = dict(commands[-1])
                plugin._handle_external_overlay_action({"type": "tab", "index": 0})
                plugin._handle_external_overlay_input("page_next")
                plugin._handle_external_overlay_action(
                    {"type": "select", "index": 2, "play": True}
                )

        self.assertEqual(tab_state["tab_index"], 1)
        self.assertEqual(tab_state["sounds"][0]["id"], "sound-40")
        self.assertEqual(
            plugin.fake_app.play_payloads,
            [{"sound_id": f"sound-{SOUNDS_PER_PAGE + 2}", "volume": None}],
        )
        self.assertFalse(commands[-1]["visible"])

    def test_replay_plays_the_last_sound_without_opening_the_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(5)
            save_recent_ids(plugin.paths.overlay_recent_file, ["sound-3", "sound-1"])
            with captured_overlay(plugin) as commands:
                response = plugin._replay_last_external_overlay_sound()

        self.assertTrue(response["ok"])
        self.assertEqual(response["sound_id"], "sound-3")
        self.assertEqual(
            plugin.fake_app.play_payloads, [{"sound_id": "sound-3", "volume": None}]
        )
        self.assertFalse(commands[-1]["visible"])
        self.assertEqual(commands[-1]["toast"], {"text": "Sound 3", "tone": "play"})

    def test_replay_without_history_explains_why_nothing_played(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.sounds = sound_items(2)
            with captured_overlay(plugin) as commands:
                response = plugin._replay_last_external_overlay_sound()

        self.assertFalse(response["ok"])
        self.assertEqual(plugin.fake_app.play_payloads, [])
        self.assertEqual(
            commands[-1]["toast"], {"text": "Nothing to replay yet", "tone": "info"}
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

    def test_stop_external_overlay_releases_grabs_and_reaps_process(self) -> None:
        process = MagicMock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin._external_overlay_process = process
            plugin._external_overlay_visible = True
            with (
                patch.object(
                    plugin, "_release_external_overlay_input_grab"
                ) as release_grab,
                patch.object(plugin, "_send_external_overlay_command") as send_command,
            ):
                plugin._stop_external_overlay()

        release_grab.assert_called_once_with()
        send_command.assert_called_once_with({"type": "quit"}, start_process=False)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=0.75)
        self.assertFalse(plugin._external_overlay_visible)
        self.assertIsNone(plugin._external_overlay_process)

    def test_automatic_mode_reads_evdev_devices_after_grab(self) -> None:
        device = {
            "id": "evdev:0000000000000001",
            "name": "Steam Deck",
            "path": "/dev/input/event4",
            "label": "Steam Deck (event4)",
        }
        fake_handle = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch("main.discover_overlay_input_devices", return_value=[device]),
                patch("main.discover_gamepad_input_devices", return_value=[device]),
                patch("main.open_nonblocking", return_value=fake_handle),
                patch("main.set_device_grab") as set_grab,
                patch.object(
                    plugin, "_start_external_overlay_evdev_reader"
                ) as start_reader,
            ):
                plugin._grab_external_overlay_input_devices()
                start_reader.assert_called_once_with()
                plugin._release_external_overlay_input_grab()

        self.assertEqual(
            [call.args for call in set_grab.call_args_list],
            [(fake_handle, True), (fake_handle, False)],
        )
        fake_handle.close.assert_called_once_with()

    def test_overlay_grab_blocks_gamepads_it_does_not_read(self) -> None:
        deck = {
            "id": "evdev:0000000000000001",
            "name": "Steam Deck",
            "path": "/dev/input/event4",
            "label": "Steam Deck (event4)",
        }
        gamepads = [
            {"name": "Steam Deck", "path": "/dev/input/event4"},
            {"name": "Microsoft X-Box 360 pad 0", "path": "/dev/input/event9"},
        ]
        handles = {path: MagicMock(name=path) for path in ("event4", "event9")}
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch("main.discover_overlay_input_devices", return_value=[deck]),
                patch("main.discover_gamepad_input_devices", return_value=gamepads),
                patch(
                    "main.open_nonblocking",
                    side_effect=lambda path: handles[Path(path).name],
                ),
                patch("main.set_device_grab") as set_grab,
                patch.object(plugin, "_start_external_overlay_evdev_reader"),
            ):
                plugin._grab_external_overlay_input_devices()
                read_paths = [
                    path
                    for path, _name, _handle in plugin._external_overlay_input_grab_handles
                ]
                plugin._release_external_overlay_input_grab()

        # Only the controller that drives the overlay is read; the Steam pad
        # is grabbed so the game stops receiving presses, then released.
        self.assertEqual(read_paths, ["/dev/input/event4"])
        self.assertCountEqual(
            [call.args for call in set_grab.call_args_list],
            [
                (handle, grabbed)
                for handle in handles.values()
                for grabbed in (True, False)
            ],
        )
        for handle in handles.values():
            handle.close.assert_called_once_with()
        self.assertEqual(plugin._external_overlay_input_block_handles, [])

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
            plugin._external_overlay_visible = True
            with (
                patch.object(plugin, "_handle_overlay_direct_hotkey") as hotkey,
                patch.object(plugin, "_handle_external_overlay_input") as action,
            ):
                plugin._handle_external_overlay_evdev_press(0x225, "/dev/input/event7")
                plugin._handle_external_overlay_evdev_press(0x223, "/dev/input/event7")

        hotkey.assert_called_once_with("evdev-grab")
        action.assert_called_once_with("right")

    def test_hid_report_edges_route_hotkey_actions_and_ignore_hidden_navigation(
        self,
    ) -> None:
        def report(buttons_l: int) -> dict[str, int]:
            return {"offset": 0, "buttons_l": buttons_l, "buttons_h": 0}

        l5 = STEAM_DECK_REAR_BUTTON_MASKS["l5"]
        a_button = STEAM_DECK_LBUTTON_A
        previous: dict[str, int] = {}
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch.object(plugin, "_handle_overlay_direct_hotkey") as hotkey,
                patch.object(
                    plugin, "_handle_external_overlay_input", return_value={}
                ) as action,
            ):
                plugin._handle_steam_deck_hid_report(
                    report(l5), "/dev/hidraw0", previous
                )
                hotkey.assert_not_called()  # first report is only a baseline

                plugin._handle_steam_deck_hid_report(
                    report(0), "/dev/hidraw0", previous
                )
                plugin._handle_steam_deck_hid_report(
                    report(l5), "/dev/hidraw0", previous
                )
                hotkey.assert_called_once_with("hidraw-input")

                plugin._handle_steam_deck_hid_report(
                    report(a_button), "/dev/hidraw0", previous
                )
                action.assert_not_called()  # overlay hidden

                plugin._external_overlay_visible = True
                plugin._handle_steam_deck_hid_report(
                    report(0), "/dev/hidraw0", previous
                )
                plugin._handle_steam_deck_hid_report(
                    report(a_button), "/dev/hidraw0", previous
                )
                action.assert_called_once_with("play")

    def test_os_hotkey_worker_reads_events_and_toggles_overlay(self) -> None:
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        reader = os.fdopen(read_fd, "rb", buffering=0)
        toggled = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            with (
                patch.object(
                    plugin,
                    "_open_input_event_devices",
                    return_value=[("/dev/input/event4", reader)],
                ),
                patch.object(
                    plugin,
                    "_handle_overlay_direct_hotkey",
                    side_effect=lambda source: toggled.set(),
                ) as hotkey,
            ):
                worker = threading.Thread(
                    target=plugin._hotkey_monitor_worker, daemon=True
                )
                worker.start()
                os.write(write_fd, INPUT_EVENT_STRUCT.pack(0, 0, EV_KEY, BTN_GRIPL2, 1))
                self.assertTrue(toggled.wait(timeout=2.0))
                plugin._hotkey_stop.set()
                worker.join(timeout=3.0)
            os.close(write_fd)

        self.assertFalse(worker.is_alive())
        hotkey.assert_called_once_with("os-input")
        self.assertTrue(reader.closed)
        joined = "\n".join(plugin._bridge_errors)
        self.assertIn("Overlay OS hotkey monitor stopped", joined)

    def test_monitor_logs_missing_devices_once_per_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            stop = threading.Event()
            waits = {"count": 0}

            def fake_wait(_timeout: float) -> bool:
                waits["count"] += 1
                if waits["count"] >= 3:
                    stop.set()
                return stop.is_set()

            stop.wait = fake_wait  # type: ignore[method-assign]
            plugin._monitor_input_devices(
                "Overlay OS hotkey monitor",
                "/dev/input/event*",
                stop,
                lambda: [],
                lambda _handles: None,
            )

        joined = "\n".join(plugin._bridge_errors)
        self.assertEqual(
            joined.count("found no readable /dev/input/event* devices"),
            1,
            joined,
        )
        self.assertEqual(waits["count"], 3)

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
        self.assertEqual(commands[0]["replay_button"], "R5")

    def test_replay_hint_is_hidden_when_r5_opens_the_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = DirectPlugin(Path(tmp))
            plugin.fake_app.settings = Settings(overlay_hotkey_button="r5")
            with captured_overlay(plugin) as commands:
                plugin._send_external_overlay_state()

        self.assertIsNone(commands[0]["replay_button"])


if __name__ == "__main__":
    unittest.main()
