from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.config import Settings  # noqa: E402
from decksoundpad import __version__  # noqa: E402
from decksoundpad.paths import AppPaths, ensure_app_dirs  # noqa: E402
from main import Plugin, _daemon_python_executable  # noqa: E402


class TestPlugin(Plugin):
    def __init__(self) -> None:
        self.logger = logging.getLogger("test")
        self.started = threading.Event()
        self.requested = False

    def _daemon_healthy(self, timeout: float = 0.5) -> bool:
        return False

    def _ensure_daemon_started(self) -> bool:
        self.started.set()
        return False

    def _request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.requested = True
        return {"ok": True}


class StaleSessionPlugin(Plugin):
    def __init__(self, root: Path, pid: int = 12345, *, process_alive: bool = True) -> None:
        self.logger = logging.getLogger("test")
        self.paths = AppPaths(
            plugin_dir=root / "plugin",
            settings_dir=root / "settings",
            runtime_dir=root / "runtime",
            log_dir=root / "logs",
            data_dir=root / "data",
            user_home=root / "home",
        )
        ensure_app_dirs(self.paths)
        self.paths.session_file.write_text(json.dumps({"pid": pid, "port": 8787}), encoding="utf-8")
        self.daemon_process = None
        self._daemon_lock = threading.Lock()
        self._last_daemon_start_attempt = 0.0
        self.started = False
        self.process_alive = process_alive

    def _process_alive(self, pid: int | None) -> bool:
        return pid is not None and self.process_alive

    def _session_process_is_decksoundpad(self, pid: int | None) -> bool:
        return False

    def _daemon_compatible(self, timeout: float = 0.5) -> bool:
        return False

    def _daemon_healthy(self, timeout: float = 0.5) -> bool:
        return False

    def _start_daemon(self) -> None:
        self.started = True


class BlockingStartPlugin(Plugin):
    def __init__(self, root: Path) -> None:
        self.logger = logging.getLogger("test")
        self.settings = Settings()
        self.paths = AppPaths(
            plugin_dir=root / "plugin",
            settings_dir=root / "settings",
            runtime_dir=root / "runtime",
            log_dir=root / "logs",
            data_dir=root / "data",
            user_home=root / "home",
        )
        ensure_app_dirs(self.paths)
        self.daemon_process = None
        self.started = threading.Event()
        self.release = threading.Event()

    def _ensure_daemon_started(self) -> bool:
        self.started.set()
        self.release.wait(timeout=2)
        return False

    def _session_process_is_decksoundpad(self, pid: int | None) -> bool:
        return False


class ExplodingStatusPlugin(Plugin):
    def __init__(self) -> None:
        self.logger = logging.getLogger("test")
        self.settings = Settings()
        self._bridge_errors: list[str] = []

    def _daemon_healthy(self, timeout: float = 0.5) -> bool:
        raise RuntimeError("status boom")


class IncompatibleDaemonPlugin(Plugin):
    def __init__(self) -> None:
        self.logger = logging.getLogger("test")
        self.settings = Settings()
        self._bridge_errors: list[str] = []
        self.started = threading.Event()
        self.requested = False

    def _daemon_healthy(self, timeout: float = 0.5) -> bool:
        return True

    def _daemon_compatible(self, timeout: float = 0.5) -> bool:
        return False

    def _request_daemon_start_background(self) -> None:
        self.started.set()

    def _request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.requested = True
        return {"daemon_running": True, "version": "old"}


class VersionProbePlugin(Plugin):
    def __init__(self, version: str | None, *, websocket_supported: bool = True) -> None:
        self.logger = logging.getLogger("test")
        self.version = version
        self.websocket_supported = websocket_supported

    def _daemon_healthy(self, timeout: float = 0.5) -> bool:
        return True

    def _request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return {"version": self.version} if self.version is not None else {}

    def _daemon_supports_websocket(self, timeout: float = 0.5) -> bool:
        return self.websocket_supported


class PostStartInitPlugin(Plugin):
    def __init__(self) -> None:
        self.logger = logging.getLogger("test")
        self._bridge_errors: list[str] = []
        self.started = False
        self.requests: list[tuple[str, str]] = []

    def _ensure_daemon_started(self) -> bool:
        self.started = True
        return True

    def _daemon_healthy(self, timeout: float = 0.5) -> bool:
        return True

    def _daemon_compatible(self, timeout: float = 0.5) -> bool:
        return True

    def _request(self, method: str, path: str, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.requests.append((method, path))
        return {"ok": True}


class MainAutoStartPlugin(Plugin):
    def __init__(self) -> None:
        self.started = False

    def _request_daemon_start_background(self) -> None:
        self.started = True


class MainBridgeTests(unittest.TestCase):
    def test_get_status_without_main_initialization_is_safe(self) -> None:
        plugin = TestPlugin()
        response = asyncio.run(plugin.get_status())
        self.assertFalse(response["daemon_running"])
        self.assertEqual(response["audio"]["state"], "offline")  # type: ignore[index]

    def test_get_status_exception_is_returned_and_logged(self) -> None:
        plugin = ExplodingStatusPlugin()
        response = asyncio.run(plugin.get_status())
        self.assertFalse(response["daemon_running"])
        self.assertIn("bridge get_status failed", response["audio"]["last_error"])  # type: ignore[index]

        logs = asyncio.run(plugin.get_logs_tail())
        joined = "\n".join(logs["lines"])
        self.assertIn("status boom", joined)

    def test_get_status_restarts_incompatible_daemon_without_proxying_to_it(self) -> None:
        plugin = IncompatibleDaemonPlugin()
        response = asyncio.run(plugin.get_status())
        self.assertFalse(response["daemon_running"])
        self.assertEqual(response["audio"]["state"], "starting")  # type: ignore[index]
        self.assertTrue(plugin.started.is_set())
        self.assertFalse(plugin.requested)

    def test_proxy_restarts_incompatible_daemon_without_forwarding_play(self) -> None:
        plugin = IncompatibleDaemonPlugin()
        response = asyncio.run(
            plugin._proxy(
                "POST",
                "/api/v1/play",
                {"sound_id": "sha1:test"},
                fallback={"ok": False, "error": "daemon unavailable"},
            )
        )
        self.assertEqual(response["ok"], False)
        self.assertTrue(plugin.started.is_set())
        self.assertFalse(plugin.requested)

    def test_daemon_compatible_requires_current_version(self) -> None:
        self.assertTrue(VersionProbePlugin(__version__)._daemon_compatible())
        self.assertFalse(VersionProbePlugin(None)._daemon_compatible())
        self.assertFalse(VersionProbePlugin("0.1.2")._daemon_compatible())
        self.assertFalse(VersionProbePlugin(__version__, websocket_supported=False)._daemon_compatible())

    def test_start_worker_initializes_audio_and_library_after_launch(self) -> None:
        plugin = PostStartInitPlugin()
        plugin._daemon_start_worker()
        self.assertTrue(plugin.started)
        self.assertEqual(
            plugin.requests,
            [
                ("POST", "/api/v1/audio/repair"),
                ("POST", "/api/v1/sounds/refresh"),
            ],
        )

    def test_main_requests_daemon_start_on_plugin_load(self) -> None:
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

    def test_proxy_does_not_start_daemon_by_default(self) -> None:
        plugin = TestPlugin()
        response = asyncio.run(
            plugin._proxy(
                "GET",
                "/api/v1/status/quick",
                fallback={"ok": False},
            )
        )
        self.assertEqual(response, {"ok": False})
        self.assertFalse(plugin.started.is_set())
        self.assertFalse(plugin.requested)

    def test_proxy_requests_daemon_start_in_background(self) -> None:
        plugin = TestPlugin()
        response = asyncio.run(
            plugin._proxy(
                "GET",
                "/api/v1/status/quick",
                fallback={"ok": False},
                start_daemon=True,
            )
        )
        self.assertEqual(response, {"ok": False})
        self.assertTrue(plugin.started.wait(timeout=1))
        self.assertFalse(plugin.requested)

    def test_start_daemon_returns_before_blocking_start_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = BlockingStartPlugin(Path(tmp))

            async def run_start() -> tuple[dict[str, object], float]:
                started_at = time.monotonic()
                response = await plugin.start_daemon()
                elapsed = time.monotonic() - started_at
                self.assertTrue(plugin.started.wait(timeout=1))
                plugin.release.set()
                return response, elapsed

            response, elapsed = asyncio.run(run_start())
            self.assertLess(elapsed, 0.3)
            self.assertEqual(response["audio"]["state"], "starting")  # type: ignore[index]

    def test_start_daemon_reuses_existing_start_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = BlockingStartPlugin(Path(tmp))

            async def run_start_twice() -> tuple[threading.Thread | None, threading.Thread | None]:
                await plugin.start_daemon()
                first = getattr(plugin, "_daemon_start_thread", None)
                await plugin.start_daemon()
                second = getattr(plugin, "_daemon_start_thread", None)
                return first, second

            try:
                first, second = asyncio.run(run_start_twice())
                self.assertIs(first, second)
                self.assertTrue(plugin.started.wait(timeout=1))
            finally:
                plugin.release.set()

    def test_get_web_access_does_not_start_daemon(self) -> None:
        plugin = TestPlugin()
        response = asyncio.run(plugin.get_web_access())
        self.assertEqual(response["url"], None)
        self.assertFalse(plugin.started.is_set())
        self.assertFalse(plugin.requested)

    def test_daemon_python_executable_uses_override(self) -> None:
        self.assertEqual(
            _daemon_python_executable({"DECKSOUNDPAD_PYTHON": "/custom/python3"}),
            "/custom/python3",
        )

    def test_daemon_python_executable_avoids_frozen_decky_loader(self) -> None:
        with (
            patch("main.sys.executable", "/home/deck/homebrew/services/PluginLoader"),
            patch("main.sys.frozen", True, create=True),
            patch("main.shutil.which", return_value="/usr/bin/python3"),
        ):
            self.assertEqual(_daemon_python_executable({}), "/usr/bin/python3")

    def test_bridge_log_is_written_to_public_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = BlockingStartPlugin(Path(tmp))
            plugin._append_bridge_log("public bridge line")

            content = plugin.paths.public_bridge_log_file.read_text(encoding="utf-8")
            self.assertIn("public bridge line", content)

    def test_stop_daemon_refuses_stale_session_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = StaleSessionPlugin(Path(tmp), pid=12345)
            with patch("main.os.kill") as kill:
                plugin._stop_daemon()

            kill.assert_not_called()
            self.assertFalse(plugin.paths.session_file.exists())

    def test_start_daemon_clears_stale_non_decksoundpad_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = StaleSessionPlugin(Path(tmp), pid=12345)
            with patch("main.os.kill") as kill:
                plugin._ensure_daemon_started()

            kill.assert_not_called()
            self.assertTrue(plugin.started)
            self.assertFalse(plugin.paths.session_file.exists())

    def test_start_daemon_clears_dead_stale_session_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = StaleSessionPlugin(Path(tmp), pid=12345, process_alive=False)
            with patch("main.os.kill") as kill:
                plugin._ensure_daemon_started()

            kill.assert_not_called()
            self.assertTrue(plugin.started)
            self.assertFalse(plugin.paths.session_file.exists())


if __name__ == "__main__":
    unittest.main()
