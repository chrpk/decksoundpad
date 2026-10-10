from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.audio_player import LowLatencyRawMixer
from decksoundpad.config import Settings, save_config
from decksoundpad.logging_setup import setup_logging
from decksoundpad.paths import AppPaths
from decksoundpad.process import subprocess_user_kwargs
from decksoundpad.safe_files import (
    UnsafePathError,
    ensure_directory,
    ensure_directory_tree,
    open_regular_file,
    set_socket_metadata,
)


class SafeFileTests(unittest.TestCase):
    def test_write_refuses_symlink_and_preserves_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.txt"
            target.write_text("original", encoding="utf-8")
            link = root / "state.json"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            with self.assertRaises(UnsafePathError):
                open_regular_file(link, "w", encoding="utf-8")

            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_directory_setup_refuses_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            link = root / "runtime"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            with self.assertRaises(UnsafePathError):
                ensure_directory(link)

    def test_directory_tree_refuses_intermediate_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "anchor"
            outside = root / "outside"
            anchor.mkdir()
            outside.mkdir()
            try:
                (anchor / "linked").symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            with self.assertRaises(UnsafePathError):
                ensure_directory_tree(anchor / "linked" / "sounds", anchor=anchor)

            self.assertFalse((outside / "sounds").exists())

    def test_config_save_refuses_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugin"
            settings_dir = root / "settings"
            plugin_dir.mkdir()
            settings_dir.mkdir()
            target = root / "sensitive.json"
            target.write_text(json.dumps({"preserve": True}), encoding="utf-8")
            try:
                (settings_dir / "config.json").symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            paths = AppPaths(
                plugin_dir=plugin_dir,
                settings_dir=settings_dir,
                runtime_dir=root / "runtime",
                log_dir=root / "logs",
                user_home=root / "home",
            )

            with self.assertRaises(UnsafePathError):
                save_config(paths, Settings(master_volume=0.5))

            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")), {"preserve": True}
            )

    def test_subprocesses_drop_root_to_user_home_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            home_stat = home.stat()
            if home_stat.st_uid == 0:
                with (
                    patch("decksoundpad.process.os.geteuid", return_value=0),
                    self.assertRaises(RuntimeError),
                ):
                    subprocess_user_kwargs(home)
                return

            with patch("decksoundpad.process.os.geteuid", return_value=0):
                kwargs = subprocess_user_kwargs(home)
            self.assertEqual(kwargs["user"], home_stat.st_uid)
            self.assertEqual(kwargs["group"], home_stat.st_gid)
            self.assertIn(home_stat.st_gid, kwargs["extra_groups"])

    def test_binary_open_returns_real_file_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sound.wav"
            path.write_bytes(b"RIFF")

            with open_regular_file(path, "rb") as handle:
                self.assertEqual(handle.read(), b"RIFF")
                self.assertTrue(os.fstat(handle.fileno()).st_mode)

    def test_root_mixer_rejects_parent_symlink_outside_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugin"
            user_home = root / "home"
            outside = root / "outside"
            plugin_dir.mkdir()
            user_home.mkdir()
            outside.mkdir()
            sound = outside / "sound.wav"
            sound.write_bytes(b"RIFF")
            link = plugin_dir / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            paths = AppPaths(
                plugin_dir=plugin_dir,
                settings_dir=root / "settings",
                runtime_dir=root / "runtime",
                log_dir=root / "logs",
                user_home=user_home,
            )
            mixer = LowLatencyRawMixer(paths=paths)
            real_fstat = os.fstat

            def root_owned_stat(descriptor: int) -> os.stat_result:
                values = list(real_fstat(descriptor))
                values[4] = user_home.stat().st_uid + 1
                return os.stat_result(values)

            with (
                patch("decksoundpad.audio_player.os.geteuid", return_value=0),
                patch(
                    "decksoundpad.audio_player.os.fstat", side_effect=root_owned_stat
                ),
                self.assertRaises(PermissionError),
            ):
                mixer._open_audio_file(link / "sound.wav")

    def test_public_logger_refuses_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = AppPaths(
                plugin_dir=root / "plugin",
                settings_dir=root / "settings",
                runtime_dir=root / "runtime",
                log_dir=root / "logs",
                user_home=root / "home",
            )
            paths.public_log_dir.mkdir(parents=True)
            target = root / "sensitive.log"
            target.write_text("original\n", encoding="utf-8")
            try:
                paths.public_backend_log_file.symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            logger = setup_logging(paths)
            try:
                logger.warning("must not reach target")
                self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
            finally:
                for handler in logger.handlers:
                    handler.close()
                logger.handlers.clear()

    def test_socket_metadata_sets_owner_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "overlay.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(path))
                set_socket_metadata(path, mode=0o600)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
