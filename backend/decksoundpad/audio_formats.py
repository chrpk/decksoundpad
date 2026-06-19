from __future__ import annotations

from pathlib import Path


DIRECT_PLAYBACK_EXTENSIONS = frozenset({".wav", ".flac", ".ogg"})
TRANSCODED_PLAYBACK_EXTENSIONS = frozenset({".mp3", ".m4a", ".aac"})
SUPPORTED_PLAYBACK_EXTENSIONS = DIRECT_PLAYBACK_EXTENSIONS | TRANSCODED_PLAYBACK_EXTENSIONS


def audio_extension(path: Path) -> str:
    return path.suffix.lower()


def can_play_supported_extension(path: Path) -> bool:
    return audio_extension(path) in SUPPORTED_PLAYBACK_EXTENSIONS
