from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import IO


class UnsafePathError(OSError):
    """Raised when a privileged file operation encounters an unsafe path."""


def ensure_directory(
    path: Path,
    *,
    mode: int | None = None,
    owner: tuple[int, int] | None = None,
) -> None:
    """Create and verify a directory without following a final symlink."""

    path.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UnsafePathError(f"refusing unsafe directory path: {path}") from exc

    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise UnsafePathError(f"expected directory path: {path}")
        if (
            owner is not None
            and hasattr(os, "fchown")
            and (not hasattr(os, "geteuid") or os.geteuid() == 0)
        ):
            os.fchown(descriptor, *owner)
        if mode is not None:
            os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def ensure_directory_tree(
    path: Path,
    *,
    anchor: Path,
    mode: int = 0o750,
    owner: tuple[int, int] | None = None,
) -> None:
    """Create a directory below an existing anchor using no-follow dirfds."""

    target = Path(os.path.abspath(path))
    trusted_anchor = Path(os.path.abspath(anchor))
    try:
        relative = target.relative_to(trusted_anchor)
    except ValueError as exc:
        raise UnsafePathError(f"directory path escapes trusted anchor: {path}") from exc

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(trusted_anchor, flags)
    except OSError as exc:
        raise UnsafePathError(f"refusing unsafe directory anchor: {anchor}") from exc

    try:
        for part in relative.parts:
            if part in {"", ".", ".."}:
                raise UnsafePathError(f"invalid directory path component: {part!r}")
            try:
                os.mkdir(part, mode=mode, dir_fd=descriptor)
            except FileExistsError:
                pass
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise UnsafePathError(f"refusing unsafe directory path: {path}") from exc
            os.close(descriptor)
            descriptor = child
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise UnsafePathError(f"expected directory path: {path}")
            if (
                owner is not None
                and hasattr(os, "fchown")
                and (not hasattr(os, "geteuid") or os.geteuid() == 0)
            ):
                os.fchown(descriptor, *owner)
            os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def open_regular_file(
    path: Path,
    mode: str,
    *,
    encoding: str | None = None,
    permissions: int = 0o600,
    enforce_permissions: bool = False,
    owner: tuple[int, int] | None = None,
) -> IO[bytes] | IO[str]:
    """Open a regular file atomically while refusing a final symlink."""

    flags = _open_flags(mode)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, permissions)
    except OSError as exc:
        raise UnsafePathError(f"refusing unsafe file path: {path}") from exc

    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise UnsafePathError(f"expected regular file path: {path}")
        if (
            owner is not None
            and hasattr(os, "fchown")
            and (not hasattr(os, "geteuid") or os.geteuid() == 0)
        ):
            os.fchown(descriptor, *owner)
        if enforce_permissions:
            os.fchmod(descriptor, permissions)
        if "b" in mode:
            return os.fdopen(descriptor, mode)
        return os.fdopen(descriptor, mode, encoding=encoding)
    except Exception:
        os.close(descriptor)
        raise


def set_socket_metadata(
    path: Path,
    *,
    owner: tuple[int, int] | None = None,
    mode: int | None = None,
) -> None:
    """Update a Unix socket without following a replacement symlink."""

    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise UnsafePathError(f"socket path is unavailable: {path}") from exc
    if not stat.S_ISSOCK(path_stat.st_mode):
        raise UnsafePathError(f"expected Unix socket path: {path}")

    if owner is not None:
        os.chown(path, *owner, follow_symlinks=False)
    if mode is not None:
        try:
            os.chmod(path, mode, follow_symlinks=False)
        except (NotImplementedError, OSError) as exc:
            raise UnsafePathError(f"could not safely set socket mode: {path}") from exc


def _open_flags(mode: str) -> int:
    normalized = mode.replace("b", "").replace("t", "")
    if normalized == "r":
        return os.O_RDONLY
    if normalized == "w":
        return os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if normalized == "a":
        return os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if normalized == "x":
        return os.O_WRONLY | os.O_CREAT | os.O_EXCL
    raise ValueError(f"unsupported secure file mode: {mode}")
