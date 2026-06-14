from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import Settings
from .models import SoundItem
from .paths import AppPaths, ensure_app_dirs, expand_user_path


class LibrarySecurityError(ValueError):
    """Raised when a requested library path escapes configured roots."""


def utc_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class SoundLibrary:
    def __init__(self, paths: AppPaths, settings: Settings):
        self.paths = paths
        self.settings = settings
        self._items: list[SoundItem] = []
        self.last_scan_at: str | None = None

    def roots(self) -> list[Path]:
        return [
            expand_user_path(value, self.paths.user_home)
            for value in self.settings.library_dirs
        ]

    def ensure_roots(self) -> None:
        for root in self.roots():
            root.mkdir(parents=True, exist_ok=True)

    def scan(self) -> list[SoundItem]:
        ensure_app_dirs(self.paths)
        self.ensure_roots()
        items: list[SoundItem] = []
        items.extend(self._scan_bundled_sounds())
        for root in self.roots():
            items.extend(self._scan_root(root))
        items.sort(key=lambda item: (item.category.lower(), item.display_name.lower()))
        self._items = items
        self.last_scan_at = datetime.now(timezone.utc).isoformat()
        self._write_cache()
        return items

    def cached_items(self) -> list[SoundItem]:
        if self._items:
            return self._items
        if not self.paths.library_cache_file.exists():
            return []
        with self.paths.library_cache_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.last_scan_at = payload.get("last_scan_at")
        self._items = [SoundItem(**item) for item in payload.get("items", [])]
        return self._items

    def get_by_id(self, sound_id: str) -> SoundItem | None:
        for item in self.cached_items():
            if item.id == sound_id:
                return item
        return None

    def assert_indexed_path(self, path: Path) -> None:
        resolved = path.resolve()
        for root in self.roots():
            root_resolved = root.resolve()
            if is_relative_to(resolved, root_resolved):
                return
        raise LibrarySecurityError(f"path is outside configured libraries: {path}")

    def _scan_bundled_sounds(self) -> list[SoundItem]:
        return list(self._scan_root(self.paths.plugin_dir / "defaults" / "sounds"))

    def _scan_root(self, root: Path) -> Iterable[SoundItem]:
        if not root.exists():
            return []
        root_resolved = root.resolve()
        items: list[SoundItem] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.settings.allowed_extensions:
                continue
            if path.is_symlink() and not self.settings.allow_symlinks_outside_libraries:
                resolved = path.resolve()
                if not is_relative_to(resolved, root_resolved):
                    continue
            try:
                items.append(self._item_for_path(path, root))
            except (OSError, ValueError):
                continue
        return items

    def _item_for_path(self, path: Path, root: Path) -> SoundItem:
        stat = path.stat()
        resolved = path.resolve()
        root_resolved = root.resolve()
        if not self.settings.allow_symlinks_outside_libraries and not is_relative_to(
            resolved, root_resolved
        ):
            raise LibrarySecurityError(f"path escapes library root: {path}")

        relative = path.relative_to(root)
        category = relative.parts[0] if len(relative.parts) > 1 else "uncategorized"
        display_name = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
        hash_input = f"{resolved}\0{stat.st_mtime_ns}\0{stat.st_size}".encode("utf-8")
        sound_id = f"sha1:{hashlib.sha1(hash_input).hexdigest()}"
        return SoundItem(
            id=sound_id,
            name=path.stem,
            display_name=display_name,
            path=str(resolved),
            relative_path=relative.as_posix(),
            category=category,
            extension=path.suffix.lower(),
            size_bytes=stat.st_size,
            modified_at=utc_from_timestamp(stat.st_mtime),
        )

    def _write_cache(self) -> None:
        payload = {
            "last_scan_at": self.last_scan_at,
            "items": [asdict(item) for item in self._items],
        }
        with self.paths.library_cache_file.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
