from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.config import Settings
from decksoundpad.library import SoundLibrary
from decksoundpad.paths import AppPaths


class LibraryTests(unittest.TestCase):
    def paths(self, root: Path) -> AppPaths:
        return AppPaths(
            plugin_dir=root,
            settings_dir=root / "settings",
            runtime_dir=root / "runtime",
            log_dir=root / "logs",
            user_home=root / "home",
        )

    def library(self, root: Path, library_dir: Path) -> SoundLibrary:
        settings = Settings(library_dirs=[str(library_dir)])
        return SoundLibrary(self.paths(root), settings)

    def test_library_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = self.library(root, root / "sounds")
            self.assertEqual(library.scan(), [])

    def test_library_lists_bundled_sounds_from_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "defaults" / "sounds" / "sample"
            bundled.mkdir(parents=True)
            (bundled / "ready.wav").write_bytes(b"wav")
            settings = Settings(library_dirs=["~/Music/DeckSoundpad"])
            library = SoundLibrary(self.paths(root), settings)
            items = library.scan()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].relative_path, "sample/ready.wav")
            self.assertEqual(items[0].path, str((bundled / "ready.wav").resolve()))
            self.assertFalse(
                (root / "home" / "Music" / "DeckSoundpad" / "sample" / "ready.wav").exists()
            )

    def test_library_lists_bundled_sounds_with_custom_library_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "defaults" / "sounds" / "sample"
            bundled.mkdir(parents=True)
            (bundled / "ready.wav").write_bytes(b"wav")
            library = self.library(root, root / "custom")
            items = library.scan()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].relative_path, "sample/ready.wav")

    def test_library_lists_bundled_assets_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "defaults" / "sounds" / "assets"
            bundled.mkdir(parents=True)
            (bundled / "payment_succes.wav").write_bytes(b"wav")
            library = self.library(root, root / "custom")
            items = library.scan()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].category, "assets")
            self.assertEqual(items[0].relative_path, "assets/payment_succes.wav")

    def test_library_nested_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sounds = root / "sounds"
            (sounds / "memes").mkdir(parents=True)
            (sounds / "memes" / "vine-boom.wav").write_bytes(b"wav")
            items = self.library(root, sounds).scan()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].category, "memes")
            self.assertEqual(items[0].display_name, "vine boom")

    def test_library_unicode_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sounds = root / "sounds"
            sounds.mkdir()
            (sounds / "привет.ogg").write_bytes(b"ogg")
            items = self.library(root, sounds).scan()
            self.assertEqual(items[0].display_name, "привет")

    def test_library_duplicate_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sounds = root / "sounds"
            (sounds / "a").mkdir(parents=True)
            (sounds / "b").mkdir()
            (sounds / "a" / "hit.wav").write_bytes(b"one")
            (sounds / "b" / "hit.wav").write_bytes(b"two")
            items = self.library(root, sounds).scan()
            self.assertEqual(len(items), 2)
            self.assertNotEqual(items[0].id, items[1].id)

    def test_library_skips_symlink_that_escapes_root_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sounds = root / "sounds"
            outside = root / "outside"
            sounds.mkdir()
            outside.mkdir()
            target = outside / "secret.wav"
            target.write_bytes(b"wav")
            link = sounds / "linked.wav"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            items = self.library(root, sounds).scan()

            self.assertEqual(items, [])

    def test_library_can_allow_symlink_that_escapes_root_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sounds = root / "sounds"
            outside = root / "outside"
            sounds.mkdir()
            outside.mkdir()
            target = outside / "allowed.wav"
            target.write_bytes(b"wav")
            link = sounds / "linked.wav"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            settings = Settings(
                library_dirs=[str(sounds)],
                allow_symlinks_outside_libraries=True,
            )
            library = SoundLibrary(self.paths(root), settings)

            items = library.scan()

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].path, str(target.resolve()))
            self.assertEqual(items[0].relative_path, "linked.wav")

    def test_legacy_cache_ignores_removed_sound_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = self.library(root, root / "sounds")
            library.paths.runtime_dir.mkdir(parents=True)
            library.paths.library_cache_file.write_text(
                json.dumps(
                    {
                        "last_scan_at": "2026-01-01T00:00:00+00:00",
                        "items": [
                            {
                                "id": "sha1:test",
                                "name": "legacy",
                                "display_name": "Legacy",
                                "path": str(root / "sounds" / "legacy.wav"),
                                "relative_path": "legacy.wav",
                                "category": "uncategorized",
                                "extension": ".wav",
                                "size_bytes": 12,
                                "modified_at": "2026-01-01T00:00:00+00:00",
                                "duration_ms": None,
                                "tags": [],
                                "volume": 1.0,
                                "favorite": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            items = library.cached_items()

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].display_name, "Legacy")
            self.assertEqual(items[0].relative_path, "legacy.wav")


if __name__ == "__main__":
    unittest.main()
