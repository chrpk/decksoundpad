from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from .config import Settings
from .models import SoundItem
from .paths import AppPaths, ensure_app_dirs, expand_user_path, user_owner
from .safe_files import ensure_directory, ensure_directory_tree, open_regular_file


class LibrarySecurityError(ValueError):
    """Raised when a library root or sound path fails a location, ownership, or symlink check."""


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

    def roots(self) -> list[Path]:
        return [
            expand_user_path(value, self.paths.user_home)
            for value in self.settings.library_dirs
        ]

    def ensure_roots(self) -> None:
        for root in self.roots():
            if root.exists():
                self._validated_user_root(root)
                ensure_directory(root)
                continue

            owner = user_owner(self.paths)
            if owner is None:
                raise LibrarySecurityError(
                    "could not resolve the Steam user for library setup"
                )
            anchor = root.parent
            while not anchor.exists() and anchor != anchor.parent:
                anchor = anchor.parent
            self._validated_user_root(anchor)
            ensure_directory_tree(root, anchor=anchor, owner=owner)
            self._validated_user_root(root)

    def scan(self) -> list[SoundItem]:
        ensure_app_dirs(self.paths)
        self.ensure_roots()
        items: list[SoundItem] = []
        items.extend(self._scan_bundled_sounds())
        for root in self.roots():
            items.extend(self._scan_root(root))
        items.sort(key=lambda item: (item.category.lower(), item.display_name.lower()))
        self._items = items
        self._write_cache()
        return items

    def cached_items(self) -> list[SoundItem]:
        if self._items:
            return self._items
        if not self.paths.library_cache_file.exists():
            return []
        with open_regular_file(
            self.paths.library_cache_file,
            "r",
            encoding="utf-8",
        ) as handle:
            payload = json.load(handle)
        self._items = [
            item
            for item in (
                sound_item_from_cache(entry) for entry in payload.get("items", [])
            )
            if item is not None
        ]
        return self._items

    def get_by_id(self, sound_id: str) -> SoundItem | None:
        for item in self.cached_items():
            if item.id == sound_id:
                return item
        return None

    def _scan_bundled_sounds(self) -> list[SoundItem]:
        return list(
            self._scan_root(
                self.paths.plugin_dir / "defaults" / "sounds",
                allow_non_user_owned=True,
            )
        )

    def _scan_root(
        self,
        root: Path,
        *,
        allow_non_user_owned: bool = False,
    ) -> Iterable[SoundItem]:
        if not root.exists():
            return []
        if not allow_non_user_owned:
            self._validated_user_root(root)
        root_resolved = root.resolve()
        items: list[SoundItem] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.settings.allowed_extensions:
                continue
            if path.is_symlink() and not self.settings.allow_symlinks_outside_libraries:
                resolved = path.resolve()
                # A library symlink can point outside the chosen folder; skip it
                # unless the user has explicitly opted into that wider access.
                if not is_relative_to(resolved, root_resolved):
                    continue
            try:
                items.append(
                    self._item_for_path(
                        path,
                        root,
                        allow_non_user_owned=allow_non_user_owned,
                    )
                )
            except (OSError, ValueError):
                continue
        return items

    def _item_for_path(
        self,
        path: Path,
        root: Path,
        *,
        allow_non_user_owned: bool = False,
    ) -> SoundItem:
        path_stat = path.stat()
        resolved = path.resolve()
        root_resolved = root.resolve()
        if not self.settings.allow_symlinks_outside_libraries and not is_relative_to(
            resolved, root_resolved
        ):
            raise LibrarySecurityError(f"path escapes library root: {path}")
        owner = user_owner(self.paths)
        if not allow_non_user_owned and (owner is None or path_stat.st_uid != owner[0]):
            raise LibrarySecurityError(
                f"sound file is not owned by the Steam user: {path}"
            )

        relative = path.relative_to(root)
        category = relative.parts[0] if len(relative.parts) > 1 else "uncategorized"
        display_name = (
            path.stem.replace("_", " ").replace("-", " ").strip() or path.name
        )
        # Include mtime and size so a replaced file gets a fresh id even when it
        # keeps the same path and display name.
        hash_input = (
            f"{resolved}\0{path_stat.st_mtime_ns}\0{path_stat.st_size}".encode()
        )
        # This digest is a stable cache/UI identifier, not a security primitive.
        sound_id = f"sha1:{hashlib.sha1(hash_input, usedforsecurity=False).hexdigest()}"
        return SoundItem(
            id=sound_id,
            display_name=display_name,
            path=str(resolved),
            relative_path=relative.as_posix(),
            category=category,
            extension=path.suffix.lower(),
        )

    def _validated_user_root(self, root: Path) -> Path:
        try:
            if root.is_symlink():
                raise LibrarySecurityError(
                    f"library root must not be a symlink: {root}"
                )
            resolved = root.resolve(strict=True)
            root_stat = resolved.stat()
        except OSError as exc:
            raise LibrarySecurityError(f"library root is unavailable: {root}") from exc
        owner = user_owner(self.paths)
        if owner is None or root_stat.st_uid != owner[0]:
            raise LibrarySecurityError(
                f"library root is not owned by the Steam user: {root}"
            )
        if not resolved.is_dir():
            raise LibrarySecurityError(f"library root is not a directory: {root}")
        return resolved

    def _write_cache(self) -> None:
        payload = {
            "items": [asdict(item) for item in self._items],
        }
        with open_regular_file(
            self.paths.library_cache_file,
            "w",
            encoding="utf-8",
            permissions=0o600,
            enforce_permissions=True,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")


def sound_item_from_cache(value: object) -> SoundItem | None:
    if not isinstance(value, dict):
        return None
    try:
        sound_id = str(value["id"])
        path = str(value["path"])
        relative_path = str(value["relative_path"])
        extension = str(value["extension"])
    except KeyError:
        return None

    display_name = str(
        value.get("display_name")
        or value.get("name")
        or Path(relative_path).stem
        or Path(path).stem
    )
    return SoundItem(
        id=sound_id,
        display_name=display_name,
        path=path,
        relative_path=relative_path,
        category=str(value.get("category") or "uncategorized"),
        extension=extension,
    )
