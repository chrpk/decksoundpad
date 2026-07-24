from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .audio_formats import audio_extension, can_play_supported_extension
from .audio_router import MIC_NAME, SINK_NAME
from .config import Settings
from .models import AudioStatus
from .paths import AppPaths


def simulation_enabled(env: Mapping[str, str] | None = None) -> bool:
    value = (env or os.environ).get("DECKSOUNDPAD_SIMULATE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SimulatedAudioRouter:
    def __init__(self, _paths: AppPaths, _settings: Settings):
        self._default_source = "simulated_real_mic"
        self._ensured = True

    def ensure(self) -> AudioStatus:
        self._ensured = True
        return self.healthcheck()

    def healthcheck(self) -> AudioStatus:
        return AudioStatus(
            pipewire_available=True,
            pactl_available=True,
            sink_exists=self._ensured,
            virtual_mic_exists=self._ensured,
            loopback_exists=self._ensured,
            selected_real_mic="simulated_real_mic",
            selected_real_mic_description="Steam Deck Microphone",
            default_source=self._default_source,
            is_default_source=self._default_source == MIC_NAME,
            last_error=None,
            state="ready",
        )

    def repair(self) -> AudioStatus:
        self._ensured = True
        return self.healthcheck()


class SimulatedBackend:
    name = "simulated"

    def is_available(self) -> bool:
        return True

    def can_play(self, path: Path) -> bool:
        return can_play_supported_extension(path)

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        route = target or "current_output"
        return ["simulate-playback", f"--route={route}", f"--volume={volume:.3f}", str(path)]


@dataclass
class SimulatedPlayback:
    playback_id: str
    sound_id: str
    path: Path
    volume: float
    started_at: float


class SimulatedPlaybackManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.backends = [SimulatedBackend()]
        self.playbacks: dict[str, SimulatedPlayback] = {}

    def play(
        self,
        sound_id: str,
        path: Path,
        volume: float | None = None,
    ) -> str:
        suffix = audio_extension(path)
        backend = self.backends[0]
        if not backend.can_play(path):
            raise RuntimeError(f"no simulated playback backend can play {suffix}")

        self._collect_expired()

        if self.settings.overlap_mode == "single":
            self.stop_all()
        elif self.settings.overlap_mode == "per_sound":
            self._stop_sound(sound_id)
        elif len(self.playbacks) >= self.settings.max_concurrent_sounds:
            raise RuntimeError("maximum concurrent sounds reached")

        playback_id = f"sim_pb_{time.time_ns()}"
        self.playbacks[playback_id] = SimulatedPlayback(
            playback_id=playback_id,
            sound_id=sound_id,
            path=path,
            volume=volume if volume is not None else self.settings.master_volume,
            started_at=time.time(),
        )
        return playback_id

    def stop_all(self) -> None:
        self.playbacks.clear()

    def _stop_sound(self, sound_id: str) -> None:
        for playback_id, playback in list(self.playbacks.items()):
            if playback.sound_id == sound_id:
                self.playbacks.pop(playback_id, None)

    def _collect_expired(self) -> None:
        now = time.time()
        for playback_id, playback in list(self.playbacks.items()):
            if now - playback.started_at >= self.settings.max_playback_seconds:
                self.playbacks.pop(playback_id, None)
