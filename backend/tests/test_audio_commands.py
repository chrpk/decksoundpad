from __future__ import annotations

import io
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.audio_player import (
    FfmpegRawBackend,
    FfmpegPulseRawBackend,
    MpvBackend,
    PactlSampleBackend,
    Pipeline,
    PlaybackManager,
    PulsePlayBackend,
    PwPlayBackend,
    pulse_volume,
    select_backend,
    terminate_process_groups,
)
from decksoundpad.audio_router import (
    MIC_NAME,
    SINK_NAME,
    AudioRouter,
    parse_pactl_modules_json,
    parse_pactl_sources_json,
    parse_pactl_sources_short,
    source_is_real_mic,
)
from decksoundpad.config import Settings
from decksoundpad.models import AudioModule
from decksoundpad.paths import AppPaths
from decksoundpad.process import RunResult, decky_runtime_env, run_capture


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], RunResult]):
        self.responses = responses

    def run(self, args, *, timeout=5.0):  # noqa: ANN001
        return self.responses.get(tuple(args), RunResult(0, "", ""))


class SequenceRunner:
    def __init__(self, responses: dict[tuple[str, ...], list[RunResult]]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def run(self, args, *, timeout=5.0):  # noqa: ANN001
        key = tuple(args)
        self.calls.append(key)
        values = self.responses.get(key)
        if not values:
            return RunResult(0, "", "")
        if len(values) == 1:
            return values[0]
        return values.pop(0)


class TimeoutRecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def run(self, args, *, timeout=5.0):  # noqa: ANN001
        self.calls.append((tuple(args), timeout))
        return RunResult(0, "", "")


class FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):  # noqa: ANN201
        return None

    def wait(self, timeout=None):  # noqa: ANN001, ANN201
        return None


class RecordingBackend:
    name = "recording"

    def is_available(self) -> bool:
        return True

    def can_play(self, _path: Path) -> bool:
        return True

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        return ["recording-play", target or "current_output", f"{volume:.3f}", str(path)]


class FailingBackend:
    name = "failing"

    def is_available(self) -> bool:
        return True

    def can_play(self, _path: Path) -> bool:
        return True

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        _ = path, volume, target
        return [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('target sink not found'); sys.exit(7)",
        ]


class SlowSuccessBackend:
    name = "slow_success"

    def is_available(self) -> bool:
        return True

    def can_play(self, _path: Path) -> bool:
        return True

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> list[str]:
        _ = path, volume, target
        return [sys.executable, "-c", "import time; time.sleep(0.25)"]


class PipelineRecordingBackend:
    name = "pipeline_recording"

    def is_available(self) -> bool:
        return True

    def can_play(self, _path: Path) -> bool:
        return True

    def build_command(
        self, path: Path, volume: float, target: str | None = SINK_NAME
    ) -> Pipeline:
        return Pipeline(
            commands=[
                ["decode-audio", f"{volume:.3f}", str(path)],
                ["play-audio", target or "current_output"],
            ]
        )


class RecordingPlaybackManager(PlaybackManager):
    def __init__(self, settings: Settings):
        super().__init__(settings, [RecordingBackend()])
        self.spawned: list[list[str]] = []
        self.next_pid = 1000

    def _spawn(self, command):  # noqa: ANN001, ANN201
        self.spawned.append(command)
        self.next_pid += 1
        return [FakeProcess(self.next_pid)]


def temp_paths(root: Path) -> AppPaths:
    return AppPaths(
        plugin_dir=root,
        settings_dir=root / "settings",
        runtime_dir=root / "runtime",
        log_dir=root / "logs",
        user_home=root / "home",
    )


class AudioCommandTests(unittest.TestCase):
    def test_audio_parse_pactl_sources(self) -> None:
        output = (
            "1\talsa_input.usb-Mic\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n"
            f"2\t{SINK_NAME}.monitor\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n"
        )
        sources = parse_pactl_sources_short(output)
        self.assertEqual(sources[0].index, 1)
        self.assertEqual(sources[0].name, "alsa_input.usb-Mic")
        self.assertEqual(sources[1].name, f"{SINK_NAME}.monitor")

    def test_audio_parse_pactl_json(self) -> None:
        sources = parse_pactl_sources_json(
            '[{"index":"3","name":"alsa_input.json","driver":"PipeWire",'
            '"description":"Built-in Mic",'
            '"sample_specification":"float32le 1ch 48000Hz","state":"RUNNING"}]'
        )
        self.assertEqual(sources[0].index, 3)
        self.assertEqual(sources[0].name, "alsa_input.json")
        self.assertEqual(sources[0].description, "Built-in Mic")
        self.assertEqual(sources[0].sample_spec, "float32le 1ch 48000Hz")

        modules = parse_pactl_modules_json(
            f'[{{"index":42,"name":"module-null-sink","argument":"sink_name={SINK_NAME}"}}]'
        )
        self.assertEqual(modules[0].id, 42)
        self.assertIn(SINK_NAME, modules[0].args)

    def test_audio_detect_real_mic_excludes_monitors(self) -> None:
        self.assertTrue(source_is_real_mic("alsa_input.usb-Mic"))
        self.assertFalse(source_is_real_mic("alsa_output.pci.monitor"))
        self.assertFalse(source_is_real_mic(f"{SINK_NAME}.monitor"))

    def test_audio_detect_real_mic_excludes_decksoundpad(self) -> None:
        self.assertFalse(source_is_real_mic(MIC_NAME))

    def test_audio_router_teardown_reports_unload_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(
                {
                    ("pactl", "-f", "json", "list", "modules"): RunResult(
                        0,
                        (
                            '[{"index":42,"name":"module-null-sink",'
                            f'"argument":"sink_name={SINK_NAME}"}}]'
                        ),
                        "",
                    ),
                    ("pactl", "unload-module", "42"): RunResult(
                        1,
                        "",
                        "module is busy",
                    ),
                }
            )
            router = AudioRouter(temp_paths(Path(tmp)), Settings(), runner)

            with self.assertRaisesRegex(RuntimeError, "module is busy"):
                router.teardown()

    def test_audio_router_prefers_configured_real_mic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sources = (
                f"1\t{MIC_NAME}\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n"
                f"2\t{SINK_NAME}.monitor\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n"
                "3\talsa_input.default\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n"
                "4\talsa_input.configured\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n"
            )
            runner = FakeRunner(
                {
                    ("pactl", "list", "sources", "short"): RunResult(0, sources, ""),
                    ("pactl", "get-default-source"): RunResult(
                        0, f"{MIC_NAME}\n", ""
                    ),
                }
            )
            router = AudioRouter(
                temp_paths(Path(tmp)),
                Settings(selected_mic_source="alsa_input.configured"),
                runner,
            )
            self.assertEqual(router.detect_real_source(), "alsa_input.configured")

    def test_audio_router_ensure_does_not_make_virtual_mic_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = SequenceRunner(
                {
                    ("pactl", "info"): [
                        RunResult(0, "Server Name: PulseAudio (on PipeWire)\n", ""),
                    ],
                    (
                        "pactl",
                        "-f",
                        "json",
                        "list",
                        "sinks",
                    ): [
                        RunResult(
                            0,
                            f'[{{"index":2,"name":"{SINK_NAME}",'
                            f'"description":"DeckSoundpad internal mix bus"}}]',
                            "",
                        )
                    ],
                    (
                        "pactl",
                        "-f",
                        "json",
                        "list",
                        "sources",
                    ): [
                        RunResult(
                            0,
                            (
                                '[{"index":3,"name":"alsa_input.mic",'
                                '"description":"Steam Deck Mic"},'
                                f'{{"index":4,"name":"{MIC_NAME}",'
                                f'"description":"DeckSoundpad mic"}}]'
                            ),
                            "",
                        )
                    ],
                    (
                        "pactl",
                        "-f",
                        "json",
                        "list",
                        "modules",
                    ): [
                        RunResult(
                            0,
                            (
                                '[{"index":9,"name":"module-loopback",'
                                f'"argument":"source=alsa_input.mic sink={SINK_NAME}"}}]'
                            ),
                            "",
                        )
                    ],
                    ("pactl", "get-default-source"): [
                        RunResult(0, "alsa_input.mic\n", ""),
                    ],
                }
            )
            router = AudioRouter(temp_paths(Path(tmp)), Settings(), runner)

            with patch("decksoundpad.audio_router.command_exists", return_value=True):
                status = router.ensure()

        self.assertEqual(status.default_source, "alsa_input.mic")
        self.assertFalse(status.is_default_source)
        self.assertNotIn(("pactl", "set-default-source", MIC_NAME), runner.calls)

    def test_audio_status_reports_virtual_mic_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(
                {
                    ("pactl", "info"): RunResult(0, "Server Name: PulseAudio (on PipeWire)\n", ""),
                    (
                        "pactl",
                        "-f",
                        "json",
                        "list",
                        "sinks",
                    ): RunResult(
                        0,
                        (
                            '[{"index":1,"name":"alsa_output.speakers",'
                            '"description":"Steam Deck Speakers"},'
                            f'{{"index":2,"name":"{SINK_NAME}","description":"DeckSoundpad internal mix bus"}}]'
                        ),
                        "",
                    ),
                    (
                        "pactl",
                        "-f",
                        "json",
                        "list",
                        "sources",
                    ): RunResult(
                        0,
                        (
                            '[{"index":3,"name":"alsa_input.mic","description":"Steam Deck Mic"},'
                            f'{{"index":4,"name":"{MIC_NAME}","description":"DeckSoundpad mic"}},'
                            f'{{"index":5,"name":"{SINK_NAME}.monitor"}}]'
                        ),
                        "",
                    ),
                    (
                        "pactl",
                        "-f",
                        "json",
                        "list",
                        "modules",
                    ): RunResult(
                        0,
                        (
                            '[{"index":9,"name":"module-loopback",'
                            f'"argument":"source=alsa_input.mic sink={SINK_NAME}"}}]'
                        ),
                        "",
                    ),
                    ("pactl", "get-default-source"): RunResult(0, f"{MIC_NAME}\n", ""),
                    ("pactl", "get-default-sink"): RunResult(0, "alsa_output.speakers\n", ""),
                }
            )
            router = AudioRouter(temp_paths(Path(tmp)), Settings(), runner)
            with patch("decksoundpad.audio_router.command_exists", return_value=True):
                status = router.healthcheck()

            self.assertEqual(status.selected_real_mic, "alsa_input.mic")
            self.assertEqual(status.selected_real_mic_description, "Steam Deck Mic")
            self.assertEqual(status.state, "ready")

    def test_audio_router_falls_back_to_remap_source_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sources = f"9\t{MIC_NAME}\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n"
            runner = SequenceRunner(
                {
                    (
                        "pactl",
                        "load-module",
                        "module-virtual-source",
                        f"master={SINK_NAME}.monitor",
                        f"source_name={MIC_NAME}",
                        "source_properties=device.description=DeckSoundpad mic",
                    ): [RunResult(1, "", "module not available")],
                    (
                        "pactl",
                        "load-module",
                        "module-remap-source",
                        f"master={SINK_NAME}.monitor",
                        f"source_name={MIC_NAME}",
                        "source_properties=device.description=DeckSoundpad mic",
                    ): [RunResult(0, "42\n", "")],
                    ("pactl", "list", "sources", "short"): [
                        RunResult(0, sources, "")
                    ],
                }
            )
            router = AudioRouter(temp_paths(Path(tmp)), Settings(), runner)
            self.assertEqual(router._load_remap_source(), 42)
            self.assertIn(
                (
                    "pactl",
                    "load-module",
                    "module-remap-source",
                    f"master={SINK_NAME}.monitor",
                    f"source_name={MIC_NAME}",
                    "source_properties=device.description=DeckSoundpad mic",
                ),
                runner.calls,
            )

    def test_audio_router_detects_virtual_source_fallback_module(self) -> None:
        router = AudioRouter(temp_paths(Path("/tmp/decksoundpad-test")), Settings())
        module = router._remap_module(
            [
                AudioModule(
                    id=42,
                    name="module-virtual-source",
                    args=f"master={SINK_NAME}.monitor source_name={MIC_NAME}",
                )
            ]
        )
        self.assertIsNotNone(module)

    def test_audio_router_loads_legacy_module_state_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = temp_paths(Path(tmp))
            paths.module_state_file.parent.mkdir(parents=True, exist_ok=True)
            paths.module_state_file.write_text(
                (
                    '{"null_sink_module_id":7,'
                    '"remap_source_module_id":8,'
                    '"loopback_module_id":9,'
                    '"created_at":"unused"}'
                ),
                encoding="utf-8",
            )

            state = AudioRouter(paths, Settings())._load_module_state()

        self.assertEqual(state.null_sink_module_id, 7)
        self.assertEqual(state.remap_source_module_id, 8)
        self.assertEqual(state.loopback_module_id, 9)
        self.assertFalse(hasattr(state, "created_at"))

    def test_audio_waits_use_fast_short_pactl_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = TimeoutRecordingRunner()
            router = AudioRouter(temp_paths(Path(tmp)), Settings(), runner)
            self.assertFalse(router._wait_for_source(MIC_NAME, attempts=2, delay_seconds=0))

        self.assertEqual(
            [call[0] for call in runner.calls],
            [
                ("pactl", "list", "sources", "short"),
                ("pactl", "list", "sources", "short"),
            ],
        )
        self.assertTrue(all(timeout <= 0.75 for _, timeout in runner.calls))

    def test_run_capture_returns_timeout_result(self) -> None:
        result = run_capture(
            [sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.01
        )
        self.assertEqual(result.returncode, 124)
        self.assertIn("timeout after", result.stderr)

    def test_run_capture_accepts_explicit_env(self) -> None:
        result = run_capture(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('DECKSOUNDPAD_TEST_ENV', ''))",
            ],
            timeout=1,
            env={"DECKSOUNDPAD_TEST_ENV": "ok"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_decky_runtime_env_sets_audio_bus_defaults(self) -> None:
        env = decky_runtime_env({})
        self.assertIn("XDG_RUNTIME_DIR", env)
        self.assertEqual(
            env["DBUS_SESSION_BUS_ADDRESS"],
            f"unix:path={env['XDG_RUNTIME_DIR']}/bus",
        )
        self.assertEqual(
            env["PULSE_SERVER"],
            f"unix:{env['XDG_RUNTIME_DIR']}/pulse/native",
        )

    def test_decky_runtime_env_preserves_explicit_pulse_server(self) -> None:
        env = decky_runtime_env(
            {
                "XDG_RUNTIME_DIR": "/tmp/decksoundpad-runtime",
                "PULSE_SERVER": "tcp:127.0.0.1:4713",
            }
        )
        self.assertEqual(env["PULSE_SERVER"], "tcp:127.0.0.1:4713")

    def test_player_backend_detection(self) -> None:
        with patch("decksoundpad.audio_player.command_exists") as exists:
            exists.side_effect = lambda command: command in {"pw-play", "ffmpeg"}
            self.assertIsInstance(
                select_backend(Path("sound.wav"), [PwPlayBackend(), FfmpegRawBackend()]),
                PwPlayBackend,
            )
            self.assertIsInstance(
                select_backend(Path("sound.mp3"), [PwPlayBackend(), FfmpegRawBackend()]),
                FfmpegRawBackend,
            )

    def test_default_backend_detection_prefers_pulse_sink_clients(self) -> None:
        with patch("decksoundpad.audio_player.command_exists") as exists:
            exists.side_effect = lambda command: command in {"paplay", "pacat", "ffmpeg", "pw-play"}
            self.assertIsInstance(select_backend(Path("sound.wav")), PulsePlayBackend)
            self.assertIsInstance(select_backend(Path("sound.mp3")), FfmpegPulseRawBackend)

    def test_default_backend_detection_prefers_streaming_before_pactl_sample(self) -> None:
        with patch("decksoundpad.audio_player.command_exists") as exists:
            exists.side_effect = lambda command: command in {"pactl", "pw-play", "ffmpeg"}
            self.assertIsInstance(select_backend(Path("sound.wav")), PwPlayBackend)
            self.assertIsInstance(select_backend(Path("sound.mp3")), FfmpegRawBackend)

    def test_default_backend_detection_uses_pactl_sample_as_fallback(self) -> None:
        with patch("decksoundpad.audio_player.command_exists") as exists:
            exists.side_effect = lambda command: command in {"pactl", "ffmpeg"}
            self.assertIsInstance(select_backend(Path("sound.wav")), PactlSampleBackend)
            self.assertIsInstance(select_backend(Path("sound.mp3")), PactlSampleBackend)

    def test_pulse_playback_commands_target_virtual_mic_sink_by_default(self) -> None:
        command = PulsePlayBackend().build_command(Path("sound.wav"), 1.0)
        self.assertIn(f"--device={SINK_NAME}", command)
        self.assertIn("--volume=65536", command)

    def test_pulse_playback_commands_can_use_current_output(self) -> None:
        pulse_command = PulsePlayBackend().build_command(Path("sound.wav"), 1.0, target=None)
        self.assertFalse(any(value.startswith("--device=") for value in pulse_command))

        raw_command = FfmpegPulseRawBackend().build_command(Path("sound.mp3"), 0.5, target=None)
        playback_command = raw_command.commands[-1]
        self.assertFalse(any(value.startswith("--device=") for value in playback_command))
        self.assertIn("--volume=32768", playback_command)

    def test_pulse_volume_is_clamped_to_supported_range(self) -> None:
        self.assertEqual(pulse_volume(-1), 0)
        self.assertEqual(pulse_volume(1), 65536)
        self.assertEqual(pulse_volume(2), 98304)

    def test_playback_commands_target_virtual_mic_sink_by_default(self) -> None:
        command = PwPlayBackend().build_command(Path("sound.wav"), 1.0)
        self.assertIn(f"--target={SINK_NAME}", command)

    def test_playback_commands_can_use_current_output(self) -> None:
        pw_command = PwPlayBackend().build_command(Path("sound.wav"), 1.0, target=None)
        self.assertNotIn(f"--target={SINK_NAME}", pw_command)

        mpv_command = MpvBackend().build_command(Path("sound.mp3"), 1.0, target=None)
        self.assertFalse(any(value.startswith("--audio-device=") for value in mpv_command))

    def test_playback_manager_close_stops_playback_and_low_latency_stream(self) -> None:
        manager = PlaybackManager(Settings(), [RecordingBackend()])
        manager.low_latency = MagicMock()
        with patch.object(manager, "stop_all") as stop_all:
            manager.close()

        stop_all.assert_called_once_with(reason="backend_restart")
        manager.low_latency.close.assert_called_once_with()

    def test_playback_manager_close_cancels_timeout_threads(self) -> None:
        manager = PlaybackManager(Settings(), [RecordingBackend()])  # type: ignore[arg-type]
        manager.low_latency = MagicMock()
        timer = MagicMock()
        with patch("decksoundpad.audio_player.threading.Timer", return_value=timer):
            manager._schedule_playback_timeout("pb-1")
            manager.close()

        timer.start.assert_called_once_with()
        timer.cancel.assert_called_once_with()
        timer.join.assert_called_once_with(timeout=0.2)
        self.assertEqual(manager._playback_timers, {})  # type: ignore[attr-defined]

    def test_pactl_sample_backend_targets_virtual_mic_sink(self) -> None:
        command = PactlSampleBackend().build_command(Path("sound.wav"), 0.8)
        self.assertEqual(command[:3], ["sh", "-c", command[2]])
        self.assertEqual(command[-2], SINK_NAME)
        self.assertEqual(command[-1], "0.800")
        self.assertIn("pactl play-sample", command[2])

    def test_playback_process_uses_decky_runtime_env(self) -> None:
        captured_envs: list[dict[str, str]] = []

        class SpawnedProcess:
            pid = 32001
            stderr = io.BytesIO()

            def poll(self):  # noqa: ANN201
                return None

            def wait(self, timeout=None):  # noqa: ANN001, ANN201
                return None

        def fake_popen(_command, **kwargs):  # noqa: ANN001, ANN202
            captured_envs.append(kwargs["env"])
            return SpawnedProcess()

        with patch("decksoundpad.audio_player.subprocess.Popen", side_effect=fake_popen):
            manager = PlaybackManager(Settings(), [RecordingBackend()])
            manager.play("sound-1", Path("sound.wav"), volume=0.75)

        self.assertEqual(len(captured_envs), 1)
        self.assertIn("XDG_RUNTIME_DIR", captured_envs[0])
        self.assertEqual(
            captured_envs[0]["DBUS_SESSION_BUS_ADDRESS"],
            f"unix:path={captured_envs[0]['XDG_RUNTIME_DIR']}/bus",
        )
        self.assertEqual(captured_envs[0]["PULSE_SINK"], SINK_NAME)

    def test_playback_time_limit_stops_active_process(self) -> None:
        scheduled_timers = []
        terminated_groups: list[list[int]] = []

        class FakeTimer:
            def __init__(self, interval, function, args=(), kwargs=None):  # noqa: ANN001
                self.interval = interval
                self.function = function
                self.args = args
                self.kwargs = kwargs or {}
                self.daemon = False

            def start(self) -> None:
                scheduled_timers.append(self)

        class SpawnedProcess:
            pid = 34001
            stderr = io.BytesIO()

            def poll(self):  # noqa: ANN201
                return None

            def wait(self, timeout=None):  # noqa: ANN001, ANN201
                return None

        def fake_popen(_command, **_kwargs):  # noqa: ANN001, ANN202
            return SpawnedProcess()

        def fake_terminate(group_pids):  # noqa: ANN001
            terminated_groups.append(list(group_pids))

        with (
            patch("decksoundpad.audio_player.subprocess.Popen", side_effect=fake_popen),
            patch("decksoundpad.audio_player.threading.Timer", FakeTimer),
            patch("decksoundpad.audio_player.terminate_process_groups", side_effect=fake_terminate),
        ):
            manager = PlaybackManager(Settings(max_playback_seconds=2.5), [RecordingBackend()])
            playback_id = manager.play("sound-1", Path("sound.wav"), volume=0.75)

            self.assertEqual(len(scheduled_timers), 1)
            self.assertEqual(scheduled_timers[0].interval, 2.5)
            scheduled_timers[0].function(*scheduled_timers[0].args, **scheduled_timers[0].kwargs)

            self.assertTrue(playback_id.startswith("pb_"))
            self.assertEqual(terminated_groups, [[34001]])
            self.assertNotIn(playback_id, manager.playbacks)

    def test_playback_pipeline_uses_decky_runtime_env_for_every_process(self) -> None:
        captured_envs: list[dict[str, str]] = []

        class SpawnedProcess:
            def __init__(self, pid: int, has_stdout: bool):
                self.pid = pid
                self.stderr = io.BytesIO()
                self.stdout = io.BytesIO() if has_stdout else None

            def poll(self):  # noqa: ANN201
                return None

            def wait(self, timeout=None):  # noqa: ANN001, ANN201
                return None

        def fake_popen(_command, **kwargs):  # noqa: ANN001, ANN202
            captured_envs.append(kwargs["env"])
            return SpawnedProcess(
                33000 + len(captured_envs),
                kwargs.get("stdout") is subprocess.PIPE,
            )

        with patch("decksoundpad.audio_player.subprocess.Popen", side_effect=fake_popen):
            manager = PlaybackManager(Settings(), [PipelineRecordingBackend()])
            manager.play("sound-1", Path("sound.mp3"), volume=0.75)

        self.assertEqual(len(captured_envs), 2)
        self.assertIs(captured_envs[0], captured_envs[1])
        self.assertIn("XDG_RUNTIME_DIR", captured_envs[0])
        self.assertEqual(captured_envs[0]["PULSE_SINK"], SINK_NAME)

    def test_playback_spawns_virtual_mic_route(self) -> None:
        manager = RecordingPlaybackManager(Settings())
        manager.play("sound-1", Path("sound.wav"), volume=0.75)
        self.assertEqual(len(manager.spawned), 1)
        self.assertEqual(manager.spawned[0][1], SINK_NAME)

    def test_playback_reports_immediate_backend_failure(self) -> None:
        manager = PlaybackManager(Settings(), [FailingBackend()])
        with self.assertRaisesRegex(RuntimeError, "target sink not found"):
            manager.play("sound-1", Path("sound.wav"), volume=0.75)

    def test_playback_falls_back_after_immediate_backend_failure(self) -> None:
        manager = PlaybackManager(Settings(), [FailingBackend(), SlowSuccessBackend()])
        playback_id = manager.play("sound-1", Path("sound.wav"), volume=0.75)
        try:
            self.assertTrue(playback_id.startswith("pb_"))
            self.assertIn(playback_id, manager.playbacks)
        finally:
            manager.stop_all()

    def test_process_group_stop_terminates_every_pipeline_process(self) -> None:
        calls: list[tuple[int, signal.Signals]] = []

        def fake_killpg(pid: int, sig: signal.Signals) -> None:
            calls.append((pid, sig))

        terminate_process_groups(
            [100, 101],
            grace_seconds=0,
            killpg=fake_killpg,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(
            calls,
            [
                (100, signal.SIGTERM),
                (101, signal.SIGTERM),
                (100, signal.SIGKILL),
                (101, signal.SIGKILL),
            ],
        )


if __name__ == "__main__":
    unittest.main()
