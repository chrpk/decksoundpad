from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from .models import OverlapMode
from .paths import AppPaths, ensure_app_dirs
from .safe_files import open_regular_file

OverlayHotkeyButton = Literal["l4", "l5", "r4", "r5"]
VALID_OVERLAP_MODES = {"overlap", "single", "per_sound"}
VALID_OVERLAY_HOTKEY_BUTTONS = {"l4", "l5", "r4", "r5"}
OVERLAY_INPUT_DEVICE_PATTERN = re.compile(r"evdev:[0-9a-f]{16}\Z")
DEFAULT_ALLOWED_EXTENSIONS = [".wav", ".flac", ".ogg", ".mp3"]
DEFAULT_MAX_PLAYBACK_SECONDS = 30.0
MAX_PLAYBACK_SECONDS_LIMIT = 600.0


@dataclass(frozen=True)
class Settings:
    library_dirs: list[str] = field(default_factory=lambda: ["~/Music/DeckSoundpad"])
    master_volume: float = 1.0
    overlap_mode: OverlapMode = "overlap"
    max_concurrent_sounds: int = 3
    max_playback_seconds: float = DEFAULT_MAX_PLAYBACK_SECONDS
    selected_mic_source: str | None = None
    mic_passthrough_enabled: bool = True
    auto_repair_on_resume: bool = True
    background_healthcheck_enabled: bool = False
    overlay_hotkey_button: OverlayHotkeyButton = "l5"
    overlay_input_device: str = "auto"
    allowed_extensions: list[str] = field(
        default_factory=lambda: DEFAULT_ALLOWED_EXTENSIONS.copy()
    )
    allow_symlinks_outside_libraries: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open_regular_file(path, "r", encoding="utf-8") as handle:
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

    master_volume = float(merged["master_volume"])
    if master_volume < 0.0 or master_volume > 1.5:
        raise ValueError("master_volume must be between 0.0 and 1.5")

    overlap_mode = str(merged["overlap_mode"])
    if overlap_mode not in VALID_OVERLAP_MODES:
        raise ValueError(f"overlap_mode must be one of {sorted(VALID_OVERLAP_MODES)}")

    overlay_hotkey_button = str(merged["overlay_hotkey_button"]).lower()
    if overlay_hotkey_button not in VALID_OVERLAY_HOTKEY_BUTTONS:
        raise ValueError(
            "overlay_hotkey_button must be one of "
            f"{sorted(VALID_OVERLAY_HOTKEY_BUTTONS)}"
        )

    overlay_input_device = str(merged["overlay_input_device"]).lower()
    if overlay_input_device != "auto" and not OVERLAY_INPUT_DEVICE_PATTERN.fullmatch(
        overlay_input_device
    ):
        raise ValueError(
            "overlay_input_device must be 'auto' or an evdev device selector"
        )

    max_concurrent_sounds = int(merged["max_concurrent_sounds"])
    if max_concurrent_sounds < 1 or max_concurrent_sounds > 32:
        raise ValueError("max_concurrent_sounds must be between 1 and 32")

    max_playback_seconds = float(merged["max_playback_seconds"])
    if max_playback_seconds < 1.0 or max_playback_seconds > MAX_PLAYBACK_SECONDS_LIMIT:
        raise ValueError(
            f"max_playback_seconds must be between 1 and {MAX_PLAYBACK_SECONDS_LIMIT:g}"
        )

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
        master_volume=master_volume,
        overlap_mode=overlap_mode,  # type: ignore[arg-type]
        max_concurrent_sounds=max_concurrent_sounds,
        max_playback_seconds=max_playback_seconds,
        selected_mic_source=selected_mic_source,
        mic_passthrough_enabled=bool(merged["mic_passthrough_enabled"]),
        auto_repair_on_resume=bool(merged["auto_repair_on_resume"]),
        background_healthcheck_enabled=bool(merged["background_healthcheck_enabled"]),
        overlay_hotkey_button=cast(OverlayHotkeyButton, overlay_hotkey_button),
        overlay_input_device=overlay_input_device,
        allowed_extensions=normalized_extensions,
        allow_symlinks_outside_libraries=bool(
            merged["allow_symlinks_outside_libraries"]
        ),
    )


def default_settings(paths: AppPaths | None = None) -> Settings:
    if paths is None:
        return Settings()
    data = _load_json_file(paths.default_config_file)
    return validate_settings(data)


def load_config(paths: AppPaths) -> Settings:
    ensure_app_dirs(paths)
    data = default_settings(paths).to_dict()
    user_data = _load_json_file(paths.config_file)
    data.update(user_data)
    # Early builds used "single" as the implicit default; migrate only those
    # untouched configs so users who chose single-sound playback keep it.
    migrated = _should_migrate_legacy_single_mode(user_data)
    if migrated:
        data["overlap_mode"] = "overlap"
    settings = validate_settings(data)
    if not paths.config_file.exists() or migrated:
        save_config(paths, settings)
    return settings


def _should_migrate_legacy_single_mode(user_data: dict[str, Any]) -> bool:
    return (
        user_data.get("overlap_mode") == "single"
        and "max_playback_seconds" not in user_data
    )


def save_config(paths: AppPaths, settings: Settings) -> None:
    ensure_app_dirs(paths)
    with open_regular_file(
        paths.config_file,
        "w",
        encoding="utf-8",
        permissions=0o600,
        enforce_permissions=True,
    ) as handle:
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
