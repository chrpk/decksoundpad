from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import OverlapMode
from .paths import AppPaths, ensure_app_dirs


VALID_OVERLAP_MODES = {"overlap", "single", "per_sound"}
DEFAULT_ALLOWED_EXTENSIONS = [".wav", ".flac", ".ogg", ".mp3"]


@dataclass(frozen=True)
class Settings:
    library_dirs: list[str] = field(default_factory=lambda: ["~/Music/DeckSoundpad"])
    web_host: str = "0.0.0.0"
    web_port: int = 8787
    auth_enabled: bool = False
    master_volume: float = 1.0
    overlap_mode: OverlapMode = "overlap"
    max_concurrent_sounds: int = 4
    selected_mic_source: str | None = None
    mic_passthrough_enabled: bool = True
    set_default_source: bool = True
    play_to_output: bool = False
    restore_previous_default_on_unload: bool = True
    auto_repair_on_resume: bool = True
    background_healthcheck_enabled: bool = False
    allowed_extensions: list[str] = field(
        default_factory=lambda: DEFAULT_ALLOWED_EXTENSIONS.copy()
    )
    allow_symlinks_outside_libraries: bool = False
    auto_port: bool = True
    stop_daemon_on_plugin_unload: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "mic_passthrough_enabled", True)
        object.__setattr__(self, "set_default_source", True)
        object.__setattr__(self, "play_to_output", False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _normalize_extension(value: str) -> str:
    extension = value.strip().lower()
    if not extension:
        raise ValueError("extensions cannot be empty")
    if not extension.startswith("."):
        extension = f".{extension}"
    return extension


def validate_settings(data: dict[str, Any]) -> Settings:
    merged = Settings().to_dict()
    merged.update(data)

    library_dirs = merged["library_dirs"]
    if not isinstance(library_dirs, list) or not all(
        isinstance(item, str) and item.strip() for item in library_dirs
    ):
        raise ValueError("library_dirs must be a non-empty list of strings")

    web_port = int(merged["web_port"])
    if web_port < 1 or web_port > 65535:
        raise ValueError("web_port must be between 1 and 65535")

    master_volume = float(merged["master_volume"])
    if master_volume < 0.0 or master_volume > 1.5:
        raise ValueError("master_volume must be between 0.0 and 1.5")

    overlap_mode = str(merged["overlap_mode"])
    if overlap_mode not in VALID_OVERLAP_MODES:
        raise ValueError(f"overlap_mode must be one of {sorted(VALID_OVERLAP_MODES)}")

    max_concurrent_sounds = int(merged["max_concurrent_sounds"])
    if max_concurrent_sounds < 1 or max_concurrent_sounds > 32:
        raise ValueError("max_concurrent_sounds must be between 1 and 32")

    allowed_extensions = merged["allowed_extensions"]
    if not isinstance(allowed_extensions, list):
        raise ValueError("allowed_extensions must be a list")
    normalized_extensions = sorted(
        {_normalize_extension(str(extension)) for extension in allowed_extensions}
    )

    selected_mic_source = merged.get("selected_mic_source")
    if selected_mic_source is not None and not isinstance(selected_mic_source, str):
        raise ValueError("selected_mic_source must be null or a string")

    return Settings(
        library_dirs=[item.strip() for item in library_dirs],
        web_host=str(merged["web_host"]),
        web_port=web_port,
        auth_enabled=bool(merged["auth_enabled"]),
        master_volume=master_volume,
        overlap_mode=overlap_mode,  # type: ignore[arg-type]
        max_concurrent_sounds=max_concurrent_sounds,
        selected_mic_source=selected_mic_source,
        mic_passthrough_enabled=True,
        set_default_source=True,
        play_to_output=False,
        restore_previous_default_on_unload=bool(
            merged["restore_previous_default_on_unload"]
        ),
        auto_repair_on_resume=bool(merged["auto_repair_on_resume"]),
        background_healthcheck_enabled=bool(merged["background_healthcheck_enabled"]),
        allowed_extensions=normalized_extensions,
        allow_symlinks_outside_libraries=bool(
            merged["allow_symlinks_outside_libraries"]
        ),
        auto_port=bool(merged["auto_port"]),
        stop_daemon_on_plugin_unload=bool(merged["stop_daemon_on_plugin_unload"]),
    )


def default_settings(paths: AppPaths | None = None) -> Settings:
    if paths is None:
        return Settings()
    data = _load_json_file(paths.default_config_file)
    return validate_settings(data)


def load_config(paths: AppPaths) -> Settings:
    ensure_app_dirs(paths)
    data = default_settings(paths).to_dict()
    data.update(_load_json_file(paths.config_file))
    settings = validate_settings(data)
    if not paths.config_file.exists():
        save_config(paths, settings)
    return settings


def save_config(paths: AppPaths, settings: Settings) -> None:
    ensure_app_dirs(paths)
    with paths.config_file.open("w", encoding="utf-8") as handle:
        json.dump(settings.to_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")


def patch_settings(settings: Settings, patch: dict[str, Any]) -> Settings:
    allowed_keys = set(settings.to_dict().keys())
    unknown = set(patch) - allowed_keys
    if unknown:
        raise ValueError(f"unknown settings keys: {sorted(unknown)}")
    data = settings.to_dict()
    data.update(patch)
    return validate_settings(data)
