from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.config import Settings
from decksoundpad.library import LibrarySecurityError, SoundLibrary
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

    def test_library_lists_packaged_assets_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir(parents=True)
            (assets / "payment_succes.mp3").write_bytes(b"mp3")
            library = self.library(root, root / "custom")
            items = library.scan()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].category, "assets")
            self.assertEqual(items[0].relative_path, "assets/payment_succes.mp3")

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
            self.assertEqual(items[0].name, "привет")

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

    def test_library_reject_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sounds = root / "sounds"
            outside = root / "outside.wav"
            outside.write_bytes(b"x")
            library = self.library(root, sounds)
            with self.assertRaises(LibrarySecurityError):
                library.assert_indexed_path(outside)


if __name__ == "__main__":
    unittest.main()
