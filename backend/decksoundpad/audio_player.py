from __future__ import annotations

import logging
import os
import re
import signal
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from .audio_router import SINK_NAME
from .config import Settings
from .process import command_exists, decky_runtime_env, run_capture


PLAYBACK_STARTUP_GRACE_SECONDS = 0.12
SINK_INPUT_LIST_TIMEOUT = 0.75
SINK_INPUT_MOVE_TIMEOUT = 0.75


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
    direct_extensions = {".wav", ".flac", ".ogg"}

    def is_available(self) -> bool:
        return command_exists("pw-play")

    def can_play(self, path: Path) -> bool:
        return path.suffix.lower() in self.direct_extensions

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
    direct_extensions = {".wav", ".flac", ".ogg"}

    def is_available(self) -> bool:
        return command_exists("paplay")

    def can_play(self, path: Path) -> bool:
        return path.suffix.lower() in self.direct_extensions

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
        return path.suffix.lower() in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}

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
        return path.suffix.lower() in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}

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
    supported_extensions = {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}

    def is_available(self) -> bool:
        return command_exists("pactl")

    def can_play(self, path: Path) -> bool:
        suffix = path.suffix.lower()
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
        return path.suffix.lower() in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}

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


def process_group_stop_sequence(pid: int) -> list[tuple[int, signal.Signals]]:
    return [(pid, signal.SIGTERM), (pid, signal.SIGKILL)]


class PlaybackManager:
    def __init__(
        self,
        settings: Settings,
        backends: Sequence[PlayerBackend] | None = None,
        logger: logging.Logger | None = None,
    ):
        self.settings = settings
        self.backends = list(backends or default_backends())
        self.logger = logger or logging.getLogger("decksoundpad.playback")
        self.playbacks: dict[str, Playback] = {}
        self.logger.info(
            "playback backend order=%s",
            [backend.name for backend in self.backends],
        )

    def active_count(self) -> int:
        self._collect_finished()
        return len(self.playbacks)

    def play(
        self,
        sound_id: str,
        path: Path,
        volume: float | None = None,
        output_target: str | None = None,
    ) -> str:
        _ = output_target
        self._collect_finished()
        self.logger.info(
            "playback request sound_id=%s path=%s suffix=%s exists=%s active=%s overlap_mode=%s max_concurrent=%s",
            sound_id,
            path,
            path.suffix.lower(),
            path.exists(),
            len(self.playbacks),
            self.settings.overlap_mode,
            self.settings.max_concurrent_sounds,
        )
        if self.settings.overlap_mode == "single":
            self.stop_all()
        elif self.settings.overlap_mode == "per_sound":
            self.stop_sound(sound_id)
        elif len(self.playbacks) >= self.settings.max_concurrent_sounds:
            raise RuntimeError("maximum concurrent sounds reached")

        backends = candidate_backends(path, self.backends)
        self.logger.info(
            "playback backend probe sound_id=%s suffix=%s candidates=%s all_backends=%s",
            sound_id,
            path.suffix.lower(),
            [backend.name for backend in backends],
            backend_probe_for_log(path, self.backends),
        )
        if not backends:
            raise RuntimeError(f"no playback backend can play {path.suffix.lower()}")

        effective_volume = volume if volume is not None else self.settings.master_volume
        errors: list[str] = []
        for backend in backends:
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
            if audio_snapshot_logging_enabled():
                self.logger.info(
                    "playback pipewire snapshot playback_id=%s sound_id=%s snapshot=%s",
                    playback_id,
                    sound_id,
                    pipewire_stream_snapshot_for_log(),
                )
            return playback_id
        self.logger.error("playback failed sound_id=%s errors=%s", sound_id, errors)
        raise RuntimeError("playback failed: " + "; ".join(errors))

    def stop_all(self) -> None:
        for playback_id in list(self.playbacks):
            self.stop_playback(playback_id)

    def stop_sound(self, sound_id: str) -> None:
        for playback_id, playback in list(self.playbacks.items()):
            if playback.sound_id == sound_id:
                self.stop_playback(playback_id)

    def stop_playback(self, playback_id: str) -> None:
        playback = self.playbacks.pop(playback_id, None)
        if playback is None:
            return
        terminate_process_groups(playback.group_pids)
        for process in playback.processes:
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            self._close_stderr(process)

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
            )
        ]

    def _force_sink_inputs_to_virtual_mic_sink(
        self, processes: list[subprocess.Popen[bytes]]
    ) -> None:
        pids = [process.pid for process in processes]
        moved = move_sink_inputs_to_sink(pids, SINK_NAME)
        if moved:
            self.logger.info(
                "playback sink inputs pinned to DeckSoundpad mic bus sink_inputs=%s pids=%s",
                moved,
                pids,
            )
        else:
            self.logger.info(
                "no Pulse sink-inputs found to move; playback may be native PipeWire pids=%s",
                pids,
            )

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
            )
            if previous_stdout is not None:
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


def pipewire_stream_snapshot_for_log() -> dict[str, object]:
    if not command_exists("pactl"):
        return {"pactl_available": False}
    env = decky_runtime_env()
    return {
        "pactl_available": True,
        "sink_inputs": capture_for_log(["pactl", "list", "sink-inputs", "short"], env=env),
        "source_outputs": capture_for_log(["pactl", "list", "source-outputs", "short"], env=env),
    }


def move_sink_inputs_to_sink(pids: list[int], sink_name: str) -> list[int]:
    if not pids or not command_exists("pactl"):
        return []
    env = decky_runtime_env()
    result = run_capture(
        ["pactl", "list", "sink-inputs"],
        timeout=SINK_INPUT_LIST_TIMEOUT,
        env=env,
    )
    if not result.ok:
        return []
    sink_input_ids = parse_sink_input_ids_for_pids(result.stdout, pids)
    moved: list[int] = []
    for sink_input_id in sink_input_ids:
        move_result = run_capture(
            ["pactl", "move-sink-input", str(sink_input_id), sink_name],
            timeout=SINK_INPUT_MOVE_TIMEOUT,
            env=env,
        )
        if move_result.ok:
            moved.append(sink_input_id)
    return moved


def parse_sink_input_ids_for_pids(output: str, pids: list[int]) -> list[int]:
    wanted = {str(pid) for pid in pids}
    found: list[int] = []
    current_id: int | None = None
    for line in output.splitlines():
        header = re.match(r"\s*Sink Input #(\d+)", line)
        if header:
            current_id = int(header.group(1))
            continue
        if current_id is None:
            continue
        process_id = re.search(r'application\.process\.id\s*=\s*"([^"]+)"', line)
        if process_id and process_id.group(1) in wanted:
            found.append(current_id)
            current_id = None
    return found


def capture_for_log(args: Sequence[str], *, env: dict[str, str]) -> dict[str, object]:
    result = run_capture(args, timeout=0.5, env=env)
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


def terminate_process_group(
    pid: int,
    *,
    grace_seconds: float = 0.5,
    killpg=os.killpg,
    sleeper=time.sleep,
) -> None:
    try:
        killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    sleeper(grace_seconds)
    try:
        killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
