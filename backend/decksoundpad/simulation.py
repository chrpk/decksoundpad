from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .audio_router import MIC_NAME, SINK_NAME
from .config import Settings
from .models import AudioProbe, AudioSource, AudioStatus
from .paths import AppPaths


def simulation_enabled(env: Mapping[str, str] | None = None) -> bool:
    value = (env or os.environ).get("DECKSOUNDPAD_SIMULATE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SimulatedAudioRouter:
    def __init__(self, _paths: AppPaths, settings: Settings):
        self.settings = settings
        self._default_source = MIC_NAME
        self._ensured = True

    def probe(self) -> AudioProbe:
        return AudioProbe(
            pipewire_available=True,
            pactl_available=True,
            pw_play_available=True,
            ffmpeg_available=True,
            mpv_available=False,
        )

    def list_sources(self) -> list[AudioSource]:
        return [
            AudioSource(
                index=1,
                name="simulated_real_mic",
                description="Steam Deck Microphone",
                driver="simulation",
            ),
            AudioSource(index=2, name=f"{SINK_NAME}.monitor", driver="simulation"),
            AudioSource(
                index=3,
                name=MIC_NAME,
                description="DeckSoundpad mic",
                driver="simulation",
            ),
        ]

    def detect_real_sources(self) -> list[AudioSource]:
        return [self.list_sources()[0]]

    def detect_real_source(self) -> str | None:
        return "simulated_real_mic"

    def get_default_source(self) -> str | None:
        return self._default_source

    def ensure(self) -> AudioStatus:
        self._ensured = True
        self.set_default_virtual_mic()
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

    def teardown(self) -> None:
        self._ensured = False

    def set_default_virtual_mic(self) -> None:
        self._default_source = MIC_NAME

    def restore_previous_default(self) -> None:
        self._default_source = "simulated_real_mic"


class SimulatedBackend:
    name = "simulated"

    def is_available(self) -> bool:
        return True

    def can_play(self, path: Path) -> bool:
        return path.suffix.lower() in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}

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
    routes: list[str]
    started_at: float


class SimulatedPlaybackManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.backends = [SimulatedBackend()]
        self.playbacks: dict[str, SimulatedPlayback] = {}

    def active_count(self) -> int:
        return len(self.playbacks)

    def play(
        self,
        sound_id: str,
        path: Path,
        volume: float | None = None,
        output_target: str | None = None,
    ) -> str:
        _ = output_target
        suffix = path.suffix.lower()
        backend = self.backends[0]
        if not backend.can_play(path):
            raise RuntimeError(f"no simulated playback backend can play {suffix}")

        if self.settings.overlap_mode == "single":
            self.stop_all()
        elif self.settings.overlap_mode == "per_sound":
            self.stop_sound(sound_id)
        elif len(self.playbacks) >= self.settings.max_concurrent_sounds:
            raise RuntimeError("maximum concurrent sounds reached")

        playback_id = f"sim_pb_{time.time_ns()}"
        self.playbacks[playback_id] = SimulatedPlayback(
            playback_id=playback_id,
            sound_id=sound_id,
            path=path,
            volume=volume if volume is not None else self.settings.master_volume,
            routes=["virtual_mic"],
            started_at=time.time(),
        )
        return playback_id

    def stop_all(self) -> None:
        self.playbacks.clear()

    def stop_sound(self, sound_id: str) -> None:
        for playback_id, playback in list(self.playbacks.items()):
            if playback.sound_id == sound_id:
                self.playbacks.pop(playback_id, None)

    def stop_playback(self, playback_id: str) -> None:
        self.playbacks.pop(playback_id, None)
