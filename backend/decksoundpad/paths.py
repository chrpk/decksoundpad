from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


APP_ID = "decksoundpad"


@dataclass(frozen=True)
class AppPaths:
    plugin_dir: Path
    settings_dir: Path
    runtime_dir: Path
    log_dir: Path
    data_dir: Path
    user_home: Path

    @property
    def config_file(self) -> Path:
        return self.settings_dir / "config.json"

    @property
    def default_config_file(self) -> Path:
        return self.plugin_dir / "defaults" / "config.default.json"

    @property
    def token_file(self) -> Path:
        return self.settings_dir / "token"

    @property
    def session_file(self) -> Path:
        return self.runtime_dir / "session.json"

    @property
    def module_state_file(self) -> Path:
        return self.runtime_dir / "audio_modules.json"

    @property
    def library_cache_file(self) -> Path:
        return self.runtime_dir / "library_cache.json"

    @property
    def daemon_log_file(self) -> Path:
        return self.log_dir / "daemon.log"

    @property
    def plugin_log_file(self) -> Path:
        return self.log_dir / "decksoundpad.log"

    @property
    def public_log_dir(self) -> Path:
        return self.user_home / "Public" / "DeckSoundpad" / "logs"

    @property
    def public_daemon_log_file(self) -> Path:
        return self.public_log_dir / "daemon.log"

    @property
    def public_daemon_stdio_log_file(self) -> Path:
        return self.public_log_dir / "daemon-stdio.log"

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

    data_dir = user_home / ".local" / "share" / APP_ID

    return AppPaths(
        plugin_dir=resolved_plugin_dir,
        settings_dir=settings_dir,
        runtime_dir=runtime_dir,
        log_dir=log_dir,
        data_dir=data_dir,
        user_home=user_home,
    )


def ensure_app_dirs(paths: AppPaths) -> None:
    for directory in (
        paths.settings_dir,
        paths.runtime_dir,
        paths.log_dir,
        paths.data_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    try:
        paths.public_log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def expand_user_path(value: str, user_home: Path) -> Path:
    if value == "~":
        return user_home
    if value.startswith("~/"):
        return user_home / value[2:]
    return Path(value).expanduser()
