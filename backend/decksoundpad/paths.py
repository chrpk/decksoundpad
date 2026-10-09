from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .safe_files import ensure_directory

APP_ID = "decksoundpad"


@dataclass(frozen=True)
class AppPaths:
    plugin_dir: Path
    settings_dir: Path
    runtime_dir: Path
    log_dir: Path
    user_home: Path

    @property
    def config_file(self) -> Path:
        return self.settings_dir / "config.json"

    @property
    def default_config_file(self) -> Path:
        return self.plugin_dir / "defaults" / "config.default.json"

    @property
    def module_state_file(self) -> Path:
        return self.runtime_dir / "audio_modules.json"

    @property
    def library_cache_file(self) -> Path:
        return self.runtime_dir / "library_cache.json"

    @property
    def overlay_recent_file(self) -> Path:
        return self.runtime_dir / "overlay_recent.json"

    @property
    def test_beep_file(self) -> Path:
        return self.runtime_dir / "test_beep.wav"

    @property
    def backend_log_file(self) -> Path:
        return self.log_dir / "backend.log"

    @property
    def public_log_dir(self) -> Path:
        return self.user_home / "Public" / "DeckSoundpad" / "logs"

    @property
    def public_backend_log_file(self) -> Path:
        return self.public_log_dir / "backend.log"

    @property
    def public_bridge_log_file(self) -> Path:
        return self.public_log_dir / "bridge.log"


def _path_from_env(env: Mapping[str, str], key: str) -> Path | None:
    value = env.get(key)
    if not value:
        return None
    return Path(value).expanduser()


def default_plugin_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_paths(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    plugin_dir: Path | None = None,
) -> AppPaths:
    env = env or os.environ
    user_home = _path_from_env(env, "DECKY_USER_HOME") or home or Path.home()
    user_home = user_home.expanduser()

    resolved_plugin_dir = (
        _path_from_env(env, "DECKY_PLUGIN_DIR") or plugin_dir or default_plugin_dir()
    )

    settings_dir = _path_from_env(env, "DECKY_PLUGIN_SETTINGS_DIR")
    runtime_dir = _path_from_env(env, "DECKY_PLUGIN_RUNTIME_DIR")
    log_dir = _path_from_env(env, "DECKY_PLUGIN_LOG_DIR")

    if settings_dir is None:
        settings_dir = user_home / ".config" / APP_ID
    if runtime_dir is None:
        runtime_dir = user_home / ".local" / "state" / APP_ID
    if log_dir is None:
        log_dir = user_home / ".local" / "state" / APP_ID / "logs"

    return AppPaths(
        plugin_dir=resolved_plugin_dir,
        settings_dir=settings_dir,
        runtime_dir=runtime_dir,
        log_dir=log_dir,
        user_home=user_home,
    )


def ensure_app_dirs(paths: AppPaths) -> None:
    for directory in (
        paths.settings_dir,
        paths.runtime_dir,
        paths.log_dir,
    ):
        ensure_directory(directory)
    try:
        owner = user_owner(paths)
        ensure_directory(paths.public_log_dir.parent, mode=0o750, owner=owner)
        ensure_directory(paths.public_log_dir, mode=0o750, owner=owner)
    except OSError:
        pass


def user_owner(paths: AppPaths) -> tuple[int, int] | None:
    try:
        home_stat = paths.user_home.stat()
    except OSError:
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            return os.getuid(), os.getgid()
        return None
    return home_stat.st_uid, home_stat.st_gid


def expand_user_path(value: str, user_home: Path) -> Path:
    if value == "~":
        return user_home
    if value.startswith("~/"):
        return user_home / value[2:]
    return Path(value).expanduser()
