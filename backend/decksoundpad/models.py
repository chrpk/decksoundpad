from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

OverlapMode = Literal["overlap", "single", "per_sound"]


@dataclass(frozen=True)
class SoundItem:
    id: str
    display_name: str
    path: str
    relative_path: str
    category: str
    extension: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AudioSource:
    index: int | None
    name: str
    description: str | None = None
    driver: str | None = None
    sample_spec: str | None = None
    state: str | None = None


@dataclass(frozen=True)
class AudioModule:
    id: int
    name: str
    args: str


@dataclass(frozen=True)
class AudioProbe:
    pipewire_available: bool
    pactl_available: bool
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AudioStatus:
    pipewire_available: bool = False
    pactl_available: bool = False
    sink_exists: bool = False
    virtual_mic_exists: bool = False
    loopback_exists: bool = False
    selected_real_mic: str | None = None
    selected_real_mic_description: str | None = None
    default_source: str | None = None
    is_default_source: bool = False
    last_error: str | None = None
    state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlayerStatus:
    backend: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LibraryStatus:
    count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Status:
    backend_running: bool
    audio: AudioStatus
    player: PlayerStatus
    library: LibraryStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_running": self.backend_running,
            "audio": self.audio.to_dict(),
            "player": self.player.to_dict(),
            "library": self.library.to_dict(),
        }
