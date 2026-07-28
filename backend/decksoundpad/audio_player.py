from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import threading
import time
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol, cast

try:
    import audioop
except ImportError:  # pragma: no cover - audioop is present on Steam Deck Python.
    audioop = None  # type: ignore[assignment]

from .audio_formats import (
    DIRECT_PLAYBACK_EXTENSIONS,
    SUPPORTED_PLAYBACK_EXTENSIONS,
    audio_extension,
    can_play_supported_extension,
)
from .audio_router import SINK_NAME
from .config import Settings
from .paths import AppPaths
from .process import (
    command_exists,
    decky_runtime_env,
    run_capture,
    subprocess_user_kwargs,
)
from .safe_files import open_regular_file

PLAYBACK_STARTUP_GRACE_SECONDS = 0.12
LOW_LATENCY_SAMPLE_RATE = 48000
LOW_LATENCY_CHANNELS = 2
LOW_LATENCY_SAMPLE_WIDTH = 2
LOW_LATENCY_CHUNK_FRAMES = 240
LOW_LATENCY_SUPPORTED_EXTENSIONS = SUPPORTED_PLAYBACK_EXTENSIONS


@dataclass(frozen=True)
class Pipeline:
    commands: list[list[str]]


class PlayerBackend(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def can_play(self, path: Path) -> bool: ...

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str] | Pipeline: ...


class PwPlayBackend:
    name = "pw_play"
    direct_extensions = DIRECT_PLAYBACK_EXTENSIONS

    def is_available(self) -> bool:
        return command_exists("pw-play")

    def can_play(self, path: Path) -> bool:
        return audio_extension(path) in self.direct_extensions

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        command = ["pw-play"]
        if target:
            command.append(f"--target={target}")
        command.extend([f"--volume={volume:.3f}", str(path)])
        return command


def pulse_volume(volume: float) -> int:
    return round(max(0.0, min(volume, 1.5)) * 65536)


class PulsePlayBackend:
    name = "pulse_play"
    direct_extensions = DIRECT_PLAYBACK_EXTENSIONS

    def is_available(self) -> bool:
        return command_exists("paplay")

    def can_play(self, path: Path) -> bool:
        return audio_extension(path) in self.direct_extensions

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        command = ["paplay", f"--volume={pulse_volume(volume)}"]
        if target:
            command.append(f"--device={target}")
        command.append(str(path))
        return command


class FfmpegPulseRawBackend:
    name = "ffmpeg_pulse_raw"

    def is_available(self) -> bool:
        return command_exists("ffmpeg") and command_exists("pacat")

    def can_play(self, path: Path) -> bool:
        return can_play_supported_extension(path)

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> Pipeline:
        playback_command = [
            "pacat",
            "--raw",
            "--rate=48000",
            "--channels=2",
            "--format=s16le",
            f"--volume={pulse_volume(volume)}",
        ]
        if target:
            playback_command.append(f"--device={target}")
        return Pipeline(
            commands=[
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-f",
                    "s16le",
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    "-",
                ],
                playback_command,
            ]
        )


class FfmpegRawBackend:
    name = "ffmpeg_raw"

    def is_available(self) -> bool:
        return command_exists("ffmpeg") and command_exists("pw-play")

    def can_play(self, path: Path) -> bool:
        return can_play_supported_extension(path)

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> Pipeline:
        playback_command = [
            "pw-play",
            "--raw",
            "--rate=48000",
            "--channels=2",
            "--format=s16",
            f"--volume={volume:.3f}",
            "-",
        ]
        if target:
            playback_command.insert(1, f"--target={target}")
        return Pipeline(
            commands=[
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-f",
                    "s16le",
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    "-",
                ],
                playback_command,
            ]
        )


class PactlSampleBackend:
    name = "pactl_sample"
    supported_extensions = SUPPORTED_PLAYBACK_EXTENSIONS

    def is_available(self) -> bool:
        return command_exists("pactl")

    def can_play(self, path: Path) -> bool:
        suffix = audio_extension(path)
        return suffix == ".wav" or (
            suffix in self.supported_extensions and command_exists("ffmpeg")
        )

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        script = r'''
set -eu
input_file="$1"
target_sink="$2"
volume="$3"
sample_name="decksoundpad_$$_$(date +%s)"
tmp_file=""
cleanup() {
  pactl remove-sample "${sample_name}" >/dev/null 2>&1 || true
  if [ -n "${tmp_file}" ]; then
    rm -f "${tmp_file}"
  fi
}
trap cleanup EXIT
case "${input_file##*.}" in
  wav|WAV)
    wav_file="${input_file}"
    ;;
  *)
    tmp_file="${TMPDIR:-/tmp}/${sample_name}.wav"
    ffmpeg -hide_banner -loglevel error -y -i "${input_file}" -filter:a "volume=${volume}" -ar 48000 -ac 2 "${tmp_file}"
    wav_file="${tmp_file}"
    ;;
esac
pactl upload-sample "${wav_file}" "${sample_name}" >/dev/null
pactl play-sample "${sample_name}" "${target_sink}" >/dev/null
sleep 1
'''
        return [
            "sh",
            "-c",
            script,
            "decksoundpad-pactl-sample",
            str(path),
            target or SINK_NAME,
            f"{volume:.3f}",
        ]


class MpvBackend:
    name = "mpv"

    def is_available(self) -> bool:
        return command_exists("mpv")

    def can_play(self, path: Path) -> bool:
        return can_play_supported_extension(path)

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        command = [
            "mpv",
            "--no-video",
            "--really-quiet",
            "--ao=pulse",
            f"--volume={max(0, min(volume * 100, 150)):.0f}",
            str(path),
        ]
        if target:
            command.insert(4, f"--audio-device=pulse/{target}")
        return command


@dataclass
class Playback:
    playback_id: str
    sound_id: str
    backend_name: str
    path: Path
    group_pids: list[int]
    processes: list[subprocess.Popen[bytes]]


@dataclass
class QueuedSample:
    playback_id: str
    sound_id: str
    data: bytes
    offset: int = 0


class LowLatencyRawMixer:
    name = "low_latency_mixer"

    def __init__(
        self,
        logger: logging.Logger | None = None,
        paths: AppPaths | None = None,
    ):
        self.logger = logger or logging.getLogger("decksoundpad.low_latency")
        self.paths = paths
        self._lock = threading.RLock()
        self._samples: dict[tuple[Path, int, int], bytes] = {}
        self._active: list[QueuedSample] = []
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._pacat_available: bool | None = None
        self._ffmpeg_available: bool | None = None
        self._chunk_bytes = LOW_LATENCY_CHUNK_FRAMES * LOW_LATENCY_CHANNELS * LOW_LATENCY_SAMPLE_WIDTH
        self._silence = b"\x00" * self._chunk_bytes

    def is_available(self) -> bool:
        return self._has_pacat()

    def can_play(self, path: Path) -> bool:
        suffix = audio_extension(path)
        if suffix not in LOW_LATENCY_SUPPORTED_EXTENSIONS:
            return False
        if not self._has_pacat():
            return False
        if suffix == ".wav":
            return True
        return self._has_ffmpeg()

    def _has_pacat(self) -> bool:
        if self._pacat_available is None:
            self._pacat_available = command_exists("pacat")
        return self._pacat_available

    def _has_ffmpeg(self) -> bool:
        if self._ffmpeg_available is None:
            self._ffmpeg_available = command_exists("ffmpeg")
        return self._ffmpeg_available

    def _active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def play(self, sound_id: str, path: Path, volume: float) -> str:
        if not self.can_play(path):
            raise RuntimeError("low latency mixer cannot play this sound")
        data = self._sample_data(path)
        if volume != 1.0:
            if audioop is None:
                raise RuntimeError("audioop is required for low latency volume scaling")
            data = audioop.mul(data, LOW_LATENCY_SAMPLE_WIDTH, max(0.0, min(volume, 1.5)))
        self._ensure_stream()
        playback_id = f"ll_{time.time_ns()}"
        with self._lock:
            self._active.append(QueuedSample(playback_id, sound_id, data))
        return playback_id

    def stop_all(self) -> None:
        with self._lock:
            self._active.clear()

    def close(self) -> None:
        with self._lock:
            self._active.clear()
            self._samples.clear()
            self._running = False
            process = self._process
            thread = self._thread
            self._process = None
            self._thread = None
        if process is not None:
            terminate_process_groups([process.pid], grace_seconds=0.1)
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
            for stream in (process.stdin, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=1.0)

    def _stop_sound(self, sound_id: str) -> None:
        with self._lock:
            self._active = [sample for sample in self._active if sample.sound_id != sound_id]

    def _stop_playback(self, playback_id: str) -> bool:
        with self._lock:
            before = len(self._active)
            self._active = [sample for sample in self._active if sample.playback_id != playback_id]
            return len(self._active) != before

    def _sample_data(self, path: Path) -> bytes:
        key = self._cache_key(path)
        with self._lock:
            cached = self._samples.get(key)
        if cached is not None:
            return cached
        data = self._decode(path)
        with self._lock:
            # Decoding dominates first-play latency, so cache raw PCM until the
            # source file changes size or mtime.
            self._samples[key] = data
        return data

    def _cache_key(self, path: Path) -> tuple[Path, int, int]:
        with self._open_audio_file(path) as handle:
            file_stat = os.fstat(handle.fileno())
        return path.absolute(), file_stat.st_mtime_ns, file_stat.st_size

    def _decode(self, path: Path) -> bytes:
        if self._has_ffmpeg():
            return self._decode_with_ffmpeg(path)
        if audio_extension(path) == ".wav":
            return self._decode_exact_wav(path)
        raise RuntimeError("ffmpeg is required to decode compressed sounds")

    def _decode_with_ffmpeg(self, path: Path) -> bytes:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-f",
                "s16le",
                "-ac",
                str(LOW_LATENCY_CHANNELS),
                "-ar",
                str(LOW_LATENCY_SAMPLE_RATE),
                "-",
            ],
            check=False,
            capture_output=True,
            env=playback_env(),
            timeout=10,
            **subprocess_user_kwargs(self.paths.user_home if self.paths else None),
        )
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or "ffmpeg decode failed")
        return result.stdout

    def _decode_exact_wav(self, path: Path) -> bytes:
        with self._open_audio_file(path) as audio_file, wave.open(audio_file, "rb") as handle:
            if (
                handle.getframerate() != LOW_LATENCY_SAMPLE_RATE
                or handle.getnchannels() != LOW_LATENCY_CHANNELS
                or handle.getsampwidth() != LOW_LATENCY_SAMPLE_WIDTH
            ):
                raise RuntimeError("ffmpeg is required to resample wav files")
            return handle.readframes(handle.getnframes())

    def _ensure_stream(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                if self._thread is None or not self._thread.is_alive():
                    self._start_thread_locked()
                return
            self._process = self._spawn_pacat()
            self._running = True
            self._start_thread_locked()

    def _start_thread_locked(self) -> None:
        self._thread = threading.Thread(target=self._run, name="decksoundpad-low-latency-mixer", daemon=True)
        self._thread.start()

    def _spawn_pacat(self) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [
                "pacat",
                "--raw",
                f"--rate={LOW_LATENCY_SAMPLE_RATE}",
                f"--channels={LOW_LATENCY_CHANNELS}",
                "--format=s16le",
                f"--latency-msec={max(1, round(LOW_LATENCY_CHUNK_FRAMES / LOW_LATENCY_SAMPLE_RATE * 1000))}",
                f"--device={SINK_NAME}",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=playback_env(),
            **subprocess_user_kwargs(self.paths.user_home if self.paths else None),
        )

    def _open_audio_file(self, path: Path) -> IO[bytes]:
        handle = cast(IO[bytes], open_regular_file(path, "rb"))
        if self.paths is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
            return handle

        file_stat = os.fstat(handle.fileno())
        try:
            user_uid = self.paths.user_home.stat().st_uid
            resolved_path = path.resolve(strict=True)
            resolved_stat = resolved_path.stat()
            plugin_root = self.paths.plugin_dir.resolve(strict=True)
            same_file = (
                file_stat.st_dev == resolved_stat.st_dev
                and file_stat.st_ino == resolved_stat.st_ino
            )
            in_plugin = same_file and resolved_path.is_relative_to(plugin_root)
        except OSError:
            handle.close()
            raise RuntimeError("could not verify sound file ownership")
        if file_stat.st_uid != user_uid and not in_plugin:
            handle.close()
            raise PermissionError("refusing to read a non-user-owned sound file as root")
        return handle

    def _run(self) -> None:
        while True:
            with self._lock:
                process = self._process
                running = self._running
            if not running or process is None or process.stdin is None:
                return
            # Keep pacat alive with silence between samples so later triggers can
            # join the existing stream instead of spawning a fresh process.
            chunk = self._next_chunk()
            try:
                process.stdin.write(chunk)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                with self._lock:
                    self._process = None
                    self._running = False
                return

    def _next_chunk(self) -> bytes:
        with self._lock:
            active = list(self._active)
        if not active:
            return self._silence
        if audioop is None:
            return self._silence
        mixed = self._silence
        finished: set[str] = set()
        for sample in active:
            end = sample.offset + self._chunk_bytes
            piece = sample.data[sample.offset:end]
            if len(piece) < self._chunk_bytes:
                piece += b"\x00" * (self._chunk_bytes - len(piece))
                finished.add(sample.playback_id)
            mixed = audioop.add(mixed, piece, LOW_LATENCY_SAMPLE_WIDTH)
            sample.offset = end
        with self._lock:
            self._active = [sample for sample in self._active if sample.playback_id not in finished]
        return mixed


def default_backends() -> list[PlayerBackend]:
    return [
        PulsePlayBackend(),
        FfmpegPulseRawBackend(),
        PwPlayBackend(),
        FfmpegRawBackend(),
        MpvBackend(),
        PactlSampleBackend(),
    ]


def select_backend(path: Path, backends: Sequence[PlayerBackend] | None = None) -> PlayerBackend | None:
    for backend in candidate_backends(path, backends):
        return backend
    return None


def candidate_backends(
    path: Path, backends: Sequence[PlayerBackend] | None = None
) -> list[PlayerBackend]:
    candidates: list[PlayerBackend] = []
    for backend in backends or default_backends():
        if backend.is_available() and backend.can_play(path):
            candidates.append(backend)
    return candidates


class PlaybackManager:
    def __init__(
        self,
        settings: Settings,
        backends: Sequence[PlayerBackend] | None = None,
        logger: logging.Logger | None = None,
        paths: AppPaths | None = None,
    ):
        self.settings = settings
        self.paths = paths
        self.backends = list(backends or default_backends())
        self.logger = logger or logging.getLogger("decksoundpad.playback")
        self.playbacks: dict[str, Playback] = {}
        self.low_latency = LowLatencyRawMixer(
            self.logger.getChild("low_latency"),
            paths=paths,
        )
        self.logger.info(
            "playback backend order=%s",
            [backend.name for backend in self.backends],
        )

    def play(
        self,
        sound_id: str,
        path: Path,
        volume: float | None = None,
    ) -> str:
        self._collect_finished()
        suffix = audio_extension(path)
        self.logger.info(
            "playback request sound_id=%s path=%s suffix=%s exists=%s active=%s overlap_mode=%s max_concurrent=%s max_playback_seconds=%.3f",
            sound_id,
            path,
            suffix,
            path.exists(),
            len(self.playbacks),
            self.settings.overlap_mode,
            self.settings.max_concurrent_sounds,
            self.settings.max_playback_seconds,
        )
        if self.settings.overlap_mode == "single":
            self.stop_all(reason="overlap_mode_single")
        elif self.settings.overlap_mode == "per_sound":
            self._stop_sound(sound_id, reason="overlap_mode_per_sound")
        elif len(self.playbacks) + self.low_latency._active_count() >= self.settings.max_concurrent_sounds:
            raise RuntimeError("maximum concurrent sounds reached")

        effective_volume = volume if volume is not None else self.settings.master_volume
        if self.low_latency.can_play(path):
            try:
                playback_id = self.low_latency.play(sound_id, path, effective_volume)
                self.logger.info(
                    "low latency playback queued playback_id=%s sound_id=%s path=%s volume=%.3f",
                    playback_id,
                    sound_id,
                    path,
                    effective_volume,
                )
                self._schedule_playback_timeout(playback_id)
                return playback_id
            except Exception as exc:
                self.logger.warning(
                    "low latency playback unavailable sound_id=%s path=%s error=%s",
                    sound_id,
                    path,
                    exc,
                )

        backends = candidate_backends(path, self.backends)
        self.logger.info(
            "playback backend probe sound_id=%s suffix=%s candidates=%s all_backends=%s",
            sound_id,
            suffix,
            [backend.name for backend in backends],
            backend_probe_for_log(path, self.backends),
        )
        if not backends:
            raise RuntimeError(f"no playback backend can play {suffix}")

        errors: list[str] = []
        for backend in backends:
            # Backends vary across SteamOS images; try every usable backend before
            # surfacing a playback error to the UI.
            commands = [backend.build_command(path, effective_volume, target=SINK_NAME)]
            playback_id = f"pb_{time.time_ns()}"
            processes: list[subprocess.Popen[bytes]] = []
            self.logger.info(
                "playback starting playback_id=%s sound_id=%s backend=%s path=%s volume=%.3f routes=%s",
                playback_id,
                sound_id,
                backend.name,
                path,
                effective_volume,
                "DeckSoundpad mic",
            )
            try:
                for command in commands:
                    processes.extend(self._spawn(command))
                self._raise_if_startup_failed(processes)
            except Exception as exc:
                if processes:
                    terminate_process_groups(
                        [process.pid for process in processes],
                        grace_seconds=0,
                    )
                    self._wait_and_close(processes)
                errors.append(f"{backend.name}: {exc}")
                self.logger.warning(
                    "playback backend failed playback_id=%s sound_id=%s backend=%s error=%s",
                    playback_id,
                    sound_id,
                    backend.name,
                    exc,
                )
                continue
            self.playbacks[playback_id] = Playback(
                playback_id=playback_id,
                sound_id=sound_id,
                backend_name=backend.name,
                path=path,
                group_pids=[process.pid for process in processes],
                processes=processes,
            )
            self.logger.info(
                "playback started playback_id=%s sound_id=%s backend=%s pids=%s",
                playback_id,
                sound_id,
                backend.name,
                [process.pid for process in processes],
            )
            self._schedule_playback_timeout(playback_id)
            if audio_snapshot_logging_enabled():
                self.logger.info(
                    "playback pipewire snapshot playback_id=%s sound_id=%s snapshot=%s",
                    playback_id,
                    sound_id,
                    pipewire_stream_snapshot_for_log(
                        self.paths.user_home if self.paths else None
                    ),
                )
            return playback_id
        self.logger.error("playback failed sound_id=%s errors=%s", sound_id, errors)
        raise RuntimeError("playback failed: " + "; ".join(errors))

    def stop_all(self, *, reason: str = "manual_stop") -> None:
        self.low_latency.stop_all()
        for playback_id in list(self.playbacks):
            self._stop_playback(playback_id, reason=reason)

    def close(self) -> None:
        self.stop_all(reason="backend_restart")
        self.low_latency.close()

    def _stop_sound(self, sound_id: str, *, reason: str = "manual_stop") -> None:
        self.low_latency._stop_sound(sound_id)
        for playback_id, playback in list(self.playbacks.items()):
            if playback.sound_id == sound_id:
                self._stop_playback(playback_id, reason=reason)

    def _stop_playback(self, playback_id: str, *, reason: str = "manual_stop") -> None:
        if playback_id.startswith("ll_"):
            if self.low_latency._stop_playback(playback_id):
                self.logger.info(
                    "low latency playback stopped playback_id=%s reason=%s",
                    playback_id,
                    reason,
                )
            return
        playback = self.playbacks.pop(playback_id, None)
        if playback is None:
            return
        self.logger.info(
            "playback stopped playback_id=%s sound_id=%s backend=%s path=%s reason=%s",
            playback_id,
            playback.sound_id,
            playback.backend_name,
            playback.path,
            reason,
        )
        terminate_process_groups(playback.group_pids)
        for process in playback.processes:
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            self._close_stderr(process)

    def _schedule_playback_timeout(self, playback_id: str) -> None:
        timer = threading.Timer(
            self.settings.max_playback_seconds,
            self._stop_playback_due_to_time_limit,
            args=(playback_id,),
        )
        timer.daemon = True
        timer.start()

    def _stop_playback_due_to_time_limit(self, playback_id: str) -> None:
        self._stop_playback(playback_id, reason="time_limit")

    def _collect_finished(self) -> None:
        for playback_id, playback in list(self.playbacks.items()):
            if all(process.poll() is not None for process in playback.processes):
                returncodes = [process.returncode for process in playback.processes]
                stderr = [
                    text
                    for text in (read_process_stderr(process) for process in playback.processes)
                    if text
                ]
                self.logger.info(
                    "playback finished playback_id=%s sound_id=%s backend=%s path=%s returncodes=%s stderr=%s",
                    playback_id,
                    playback.sound_id,
                    playback.backend_name,
                    playback.path,
                    returncodes,
                    stderr,
                )
                self._wait_and_close(playback.processes)
                self.playbacks.pop(playback_id, None)

    def _spawn(self, command: list[str] | Pipeline) -> list[subprocess.Popen[bytes]]:
        env = playback_env()
        if isinstance(command, Pipeline):
            return self._spawn_pipeline(command, env=env)
        self.logger.info("spawning playback command command=%s", command_for_log(command))
        return [
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=env,
                **subprocess_user_kwargs(self.paths.user_home if self.paths else None),
            )
        ]

    def _spawn_pipeline(
        self,
        pipeline: Pipeline,
        *,
        env: dict[str, str],
    ) -> list[subprocess.Popen[bytes]]:
        processes: list[subprocess.Popen[bytes]] = []
        previous_stdout = None
        for index, command in enumerate(pipeline.commands):
            is_last = index == len(pipeline.commands) - 1
            self.logger.info("spawning playback command command=%s", command_for_log(command))
            process = subprocess.Popen(
                command,
                stdin=previous_stdout,
                stdout=subprocess.DEVNULL if is_last else subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=env,
                **subprocess_user_kwargs(self.paths.user_home if self.paths else None),
            )
            if previous_stdout is not None:
                # The child now owns the read side of the previous pipe; closing
                # our copy lets upstream commands receive SIGPIPE on failures.
                previous_stdout.close()
            previous_stdout = process.stdout
            processes.append(process)
        return processes

    def _raise_if_startup_failed(self, processes: list[subprocess.Popen[bytes]]) -> None:
        time.sleep(PLAYBACK_STARTUP_GRACE_SECONDS)
        failed = [process for process in processes if process.poll() not in (None, 0)]
        if not failed:
            return
        messages: list[str] = []
        for process in failed:
            stderr = b""
            if process.stderr is not None:
                try:
                    stderr = process.stderr.read()
                except OSError:
                    stderr = b""
                self._close_stderr(process)
            text = stderr.decode("utf-8", errors="replace").strip()
            if text:
                messages.append(text)
            else:
                messages.append(f"playback process exited with code {process.returncode}")
        raise RuntimeError("; ".join(messages))

    def _wait_and_close(self, processes: list[subprocess.Popen[bytes]]) -> None:
        for process in processes:
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            self._close_stderr(process)

    @staticmethod
    def _close_stderr(process: subprocess.Popen[bytes]) -> None:
        if process.stderr is None or process.stderr.closed:
            return
        try:
            process.stderr.close()
        except OSError:
            return

    def playback_backend_name(self, playback_id: str) -> str | None:
        if playback_id.startswith("ll_"):
            return self.low_latency.name
        playback = self.playbacks.get(playback_id)
        return playback.backend_name if playback else None


def command_for_log(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(value)) for value in command)


def playback_env() -> dict[str, str]:
    env = decky_runtime_env()
    env["PULSE_SINK"] = SINK_NAME
    return env


def audio_snapshot_logging_enabled() -> bool:
    return os.environ.get("DECKSOUNDPAD_DEBUG_AUDIO_SNAPSHOT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def backend_probe_for_log(path: Path, backends: Sequence[PlayerBackend]) -> list[dict[str, object]]:
    return [
        {
            "name": backend.name,
            "available": backend.is_available(),
            "can_play": backend.can_play(path),
        }
        for backend in backends
    ]


def read_process_stderr(process: subprocess.Popen[bytes]) -> str:
    if process.stderr is None or process.stderr.closed:
        return ""
    try:
        stderr = process.stderr.read()
    except OSError:
        return ""
    return stderr.decode("utf-8", errors="replace").strip()


def pipewire_stream_snapshot_for_log(user_home: Path | None = None) -> dict[str, object]:
    if not command_exists("pactl"):
        return {"pactl_available": False}
    env = decky_runtime_env()
    return {
        "pactl_available": True,
        "sink_inputs": capture_for_log(
            ["pactl", "list", "sink-inputs", "short"],
            env=env,
            user_home=user_home,
        ),
        "source_outputs": capture_for_log(
            ["pactl", "list", "source-outputs", "short"],
            env=env,
            user_home=user_home,
        ),
    }


def capture_for_log(
    args: Sequence[str],
    *,
    env: dict[str, str],
    user_home: Path | None = None,
) -> dict[str, object]:
    result = run_capture(args, timeout=0.5, env=env, user_home=user_home)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    return {
        "returncode": result.returncode,
        "stdout": stdout[-2000:] if stdout else "",
        "stderr": stderr[-800:] if stderr else "",
    }


def terminate_process_groups(
    pids: list[int],
    *,
    grace_seconds: float = 0.5,
    killpg=os.killpg,
    sleeper=time.sleep,
) -> None:
    # Playback commands run in their own sessions, so killing process groups also
    # stops helper children such as ffmpeg -> pacat pipelines.
    for pid in pids:
        try:
            killpg(pid, signal.SIGTERM)
        except (PermissionError, ProcessLookupError):
            continue
    sleeper(grace_seconds)
    for pid in pids:
        try:
            killpg(pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            continue
