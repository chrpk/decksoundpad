from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, fields, replace
from typing import Callable, Protocol, Sequence, TypeVar

from .config import Settings
from .models import AudioModule, AudioProbe, AudioSource, AudioStatus
from .paths import AppPaths, ensure_app_dirs
from .process import RunResult, command_exists, decky_runtime_env, run_capture


SINK_NAME = "decksoundpad_sink"
SINK_DESCRIPTION = "DeckSoundpad internal mix bus"
MIC_NAME = "decksoundpad_mic"
MIC_DESCRIPTION = "DeckSoundpad mic"
LOOPBACK_MEDIA_NAME = "DeckSoundpad mic passthrough"
PACTL_INFO_TIMEOUT = 1.5
PACTL_LIST_TIMEOUT = 1.2
PACTL_FAST_LIST_TIMEOUT = 0.75
PACTL_LOAD_TIMEOUT = 3.0
PACTL_UNLOAD_TIMEOUT = 1.5
PACTL_DEFAULT_TIMEOUT = 1.0
ParsedPactlResult = TypeVar("ParsedPactlResult")


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], *, timeout: float = 5.0) -> RunResult: ...


class SubprocessCommandRunner:
    def run(self, args: Sequence[str], *, timeout: float = 5.0) -> RunResult:
        return run_capture(args, timeout=timeout, env=decky_runtime_env())


@dataclass(frozen=True)
class ModuleState:
    null_sink_module_id: int | None = None
    remap_source_module_id: int | None = None
    loopback_module_id: int | None = None


def parse_pactl_sources_short(output: str) -> list[AudioSource]:
    sources: list[AudioSource] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            parts = line.split(maxsplit=4)
        if len(parts) < 2:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            index = None
        driver = parts[2] if len(parts) > 2 else None
        sample_spec = parts[3] if len(parts) > 3 else None
        state = parts[4] if len(parts) > 4 else None
        sources.append(
            AudioSource(
                index=index,
                name=parts[1],
                description=None,
                driver=driver,
                sample_spec=sample_spec,
                state=state,
            )
        )
    return sources


def parse_pactl_sources_json(output: str) -> list[AudioSource]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    sources: list[AudioSource] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        properties = entry.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        index = _optional_int(entry.get("index"))
        driver = _optional_str(entry.get("driver")) or _optional_str(properties.get("device.api"))
        description = (
            _optional_str(entry.get("description"))
            or _optional_str(properties.get("device.description"))
            or _optional_str(properties.get("node.description"))
            or name
        )
        sample_spec = (
            _optional_str(entry.get("sample_specification"))
            or _optional_str(entry.get("sample_spec"))
            or _optional_str(entry.get("sampleSpec"))
        )
        state = _optional_str(entry.get("state"))
        sources.append(
            AudioSource(
                index=index,
                name=name,
                description=description,
                driver=driver,
                sample_spec=sample_spec,
                state=state,
            )
        )
    return sources


def parse_pactl_names_short(output: str) -> set[str]:
    names: set[str] = set()
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            parts = line.split(maxsplit=2)
        if len(parts) >= 2:
            names.add(parts[1])
    return names


def parse_pactl_modules_short(output: str) -> list[AudioModule]:
    modules: list[AudioModule] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 2:
            parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        try:
            module_id = int(parts[0])
        except ValueError:
            continue
        args = parts[2] if len(parts) > 2 else ""
        modules.append(AudioModule(id=module_id, name=parts[1], args=args))
    return modules


def parse_pactl_modules_json(output: str) -> list[AudioModule]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    modules: list[AudioModule] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        module_id = _optional_int(entry.get("index"))
        name = _optional_str(entry.get("name"))
        if module_id is None or not name:
            continue
        args = _optional_str(entry.get("argument")) or _optional_str(entry.get("args")) or ""
        modules.append(AudioModule(id=module_id, name=name, args=args))
    return modules


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def source_is_real_mic(source_name: str) -> bool:
    if source_name in {MIC_NAME, f"{SINK_NAME}.monitor"}:
        return False
    if source_name.endswith(".monitor"):
        return False
    return True


def module_is_decksoundpad(module: AudioModule) -> bool:
    text = f"{module.name} {module.args}"
    return (
        SINK_NAME in text
        or MIC_NAME in text
        or SINK_DESCRIPTION in text
        or MIC_DESCRIPTION in text
        or LOOPBACK_MEDIA_NAME in text
    )


class AudioRouter:
    def __init__(
        self,
        paths: AppPaths,
        settings: Settings,
        runner: CommandRunner | None = None,
    ):
        self.paths = paths
        self.settings = settings
        self.runner = runner or SubprocessCommandRunner()

    def probe(self) -> AudioProbe:
        pactl_available = command_exists("pactl")
        pipewire_available = False
        last_error = None
        if pactl_available:
            result = self.runner.run(["pactl", "info"], timeout=PACTL_INFO_TIMEOUT)
            pipewire_available = result.ok
            if not result.ok:
                last_error = result.stderr.strip() or result.stdout.strip()
        return AudioProbe(
            pipewire_available=pipewire_available,
            pactl_available=pactl_available,
            last_error=last_error,
        )

    def list_sources(self) -> list[AudioSource]:
        return self._list_with_json_fallback(
            ["pactl", "-f", "json", "list", "sources"],
            parse_pactl_sources_json,
            ["pactl", "list", "sources", "short"],
            parse_pactl_sources_short,
            empty=[],
        )

    def list_sinks(self) -> list[AudioSource]:
        return self._list_with_json_fallback(
            ["pactl", "-f", "json", "list", "sinks"],
            parse_pactl_sources_json,
            ["pactl", "list", "sinks", "short"],
            parse_pactl_sources_short,
            empty=[],
        )

    def list_modules(self) -> list[AudioModule]:
        return self._list_with_json_fallback(
            ["pactl", "-f", "json", "list", "modules"],
            parse_pactl_modules_json,
            ["pactl", "list", "modules", "short"],
            parse_pactl_modules_short,
            empty=[],
        )

    def detect_real_source(self) -> str | None:
        return self._detect_real_source_from_sources(self.list_sources())

    def get_default_source(self) -> str | None:
        result = self.runner.run(["pactl", "get-default-source"], timeout=PACTL_DEFAULT_TIMEOUT)
        if not result.ok:
            return None
        source = result.stdout.strip()
        return source or None

    def healthcheck(self) -> AudioStatus:
        probe = self.probe()
        if not probe.pactl_available or not probe.pipewire_available:
            return AudioStatus(
                pipewire_available=probe.pipewire_available,
                pactl_available=probe.pactl_available,
                last_error=probe.last_error,
                state="unavailable",
            )

        sinks = self.list_sinks()
        sink_names = {sink.name for sink in sinks}
        sources = self.list_sources()
        source_names = {source.name for source in sources}
        modules = self.list_modules()
        selected_real_mic = self._detect_real_source_from_sources(sources)
        selected_real_mic_description = self._description_for_name(sources, selected_real_mic)
        loopback_exists = self._loopback_module(modules, source=selected_real_mic) is not None
        if not self.settings.mic_passthrough_enabled:
            loopback_exists = False
        default_source = self.get_default_source()
        recursive = any(
            module.name == "module-loopback"
            and MIC_NAME in module.args
            and SINK_NAME in module.args
            for module in modules
        )
        status = AudioStatus(
            pipewire_available=True,
            pactl_available=True,
            sink_exists=SINK_NAME in sink_names,
            virtual_mic_exists=MIC_NAME in source_names,
            loopback_exists=loopback_exists and not recursive,
            selected_real_mic=selected_real_mic,
            selected_real_mic_description=selected_real_mic_description,
            default_source=default_source,
            is_default_source=default_source == MIC_NAME,
            last_error="recursive loopback detected" if recursive else None,
        )
        return replace(status, state=self._health_state(status))

    def ensure(self) -> AudioStatus:
        status = self.healthcheck()
        if not status.pactl_available or not status.pipewire_available:
            return status

        modules = self.list_modules()
        state = self._load_module_state()

        if not status.sink_exists and self._null_sink_module(modules) is None:
            module_id = self._load_null_sink()
            state = self._store_module_id(
                state,
                "null_sink_module_id",
                module_id,
            )
            if module_id is None or not self._wait_for_sink(SINK_NAME):
                self._save_module_state(state)
                return self._with_error(
                    self.healthcheck(),
                    "DeckSoundpad internal mix bus did not appear after module-null-sink",
                )

        status = self.healthcheck()
        modules = self.list_modules()
        if not status.virtual_mic_exists and self._remap_module(modules) is None:
            module_id = self._load_remap_source()
            state = self._store_module_id(
                state,
                "remap_source_module_id",
                module_id,
            )
            if module_id is None:
                self._save_module_state(state)
                return self._with_error(
                    self.healthcheck(),
                    "DeckSoundpad mic did not appear after source module load",
                )

        status = self.healthcheck()
        modules = self.list_modules()
        if not self.settings.mic_passthrough_enabled:
            self._remove_decksoundpad_loopback(modules)

        real_source = status.selected_real_mic
        if (
            self.settings.mic_passthrough_enabled
            and real_source
            and source_is_real_mic(real_source)
            and self._loopback_module(modules) is None
        ):
            module_id = self._load_loopback(real_source)
            state = self._store_module_id(
                state,
                "loopback_module_id",
                module_id,
            )
            if module_id is None or not self._wait_for_loopback(real_source):
                self._save_module_state(state)
                return self._with_error(
                    self.healthcheck(),
                    "DeckSoundpad mic passthrough loopback did not appear",
                )

        self._save_module_state(state)
        return self.healthcheck()

    def repair(self) -> AudioStatus:
        self.teardown()
        return self.ensure()

    def teardown(self) -> None:
        modules = [module for module in self.list_modules() if module_is_decksoundpad(module)]
        for module in modules:
            self.runner.run(["pactl", "unload-module", str(module.id)], timeout=PACTL_UNLOAD_TIMEOUT)
        self._save_module_state(ModuleState())

    def _load_null_sink(self) -> int | None:
        result = self.runner.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                f"sink_name={SINK_NAME}",
                f"sink_properties=device.description={SINK_DESCRIPTION}",
            ],
            timeout=PACTL_LOAD_TIMEOUT,
        )
        return int(result.stdout.strip()) if result.ok and result.stdout.strip().isdigit() else None

    def _load_remap_source(self) -> int | None:
        module_id = self._load_source_module("module-virtual-source")
        if module_id is not None and self._wait_for_source(MIC_NAME):
            return module_id

        if module_id is not None:
            self.runner.run(["pactl", "unload-module", str(module_id)], timeout=PACTL_UNLOAD_TIMEOUT)

        fallback_module_id = self._load_source_module("module-remap-source")
        if fallback_module_id is not None and self._wait_for_source(MIC_NAME):
            return fallback_module_id
        if fallback_module_id is not None:
            self.runner.run(
                ["pactl", "unload-module", str(fallback_module_id)],
                timeout=PACTL_UNLOAD_TIMEOUT,
            )
        return None

    def _load_source_module(self, module_name: str) -> int | None:
        result = self.runner.run(
            [
                "pactl",
                "load-module",
                module_name,
                f"master={SINK_NAME}.monitor",
                f"source_name={MIC_NAME}",
                f"source_properties=device.description={MIC_DESCRIPTION}",
            ],
            timeout=PACTL_LOAD_TIMEOUT,
        )
        return int(result.stdout.strip()) if result.ok and result.stdout.strip().isdigit() else None

    def _source_exists(self, source_name: str) -> bool:
        return any(source.name == source_name for source in self._list_sources_short_fast())

    def _remove_decksoundpad_loopback(self, modules: list[AudioModule]) -> None:
        for module in modules:
            if module.name == "module-loopback" and module_is_decksoundpad(module):
                self.runner.run(
                    ["pactl", "unload-module", str(module.id)],
                    timeout=PACTL_UNLOAD_TIMEOUT,
                )

    def _sink_exists(self, sink_name: str) -> bool:
        return sink_name in self._list_sink_names_short_fast()

    def _wait_for_sink(
        self, sink_name: str, *, attempts: int = 8, delay_seconds: float = 0.15
    ) -> bool:
        return self._wait_for(
            lambda: self._sink_exists(sink_name),
            attempts=attempts,
            delay_seconds=delay_seconds,
        )

    def _wait_for_source(
        self, source_name: str, *, attempts: int = 8, delay_seconds: float = 0.15
    ) -> bool:
        return self._wait_for(
            lambda: self._source_exists(source_name),
            attempts=attempts,
            delay_seconds=delay_seconds,
        )

    def _wait_for_loopback(
        self, source: str, *, attempts: int = 6, delay_seconds: float = 0.15
    ) -> bool:
        return self._wait_for(
            lambda: self._loopback_module(self._list_modules_short_fast(), source=source) is not None,
            attempts=attempts,
            delay_seconds=delay_seconds,
        )

    @staticmethod
    def _wait_for(
        predicate: Callable[[], bool],
        *,
        attempts: int,
        delay_seconds: float,
    ) -> bool:
        for attempt in range(attempts):
            if predicate():
                return True
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
        return False

    def _list_with_json_fallback(
        self,
        json_args: list[str],
        json_parser: Callable[[str], ParsedPactlResult],
        short_args: list[str],
        short_parser: Callable[[str], ParsedPactlResult],
        *,
        empty: ParsedPactlResult,
    ) -> ParsedPactlResult:
        result = self.runner.run(json_args, timeout=PACTL_LIST_TIMEOUT)
        if result.ok and result.stdout.strip():
            parsed = json_parser(result.stdout)
            if parsed:
                return parsed
        result = self.runner.run(short_args, timeout=PACTL_LIST_TIMEOUT)
        if not result.ok:
            return empty
        return short_parser(result.stdout)

    def _load_loopback(self, source: str) -> int | None:
        result = self.runner.run(
            [
                "pactl",
                "load-module",
                "module-loopback",
                f"source={source}",
                f"sink={SINK_NAME}",
                "latency_msec=20",
                f"source_output_properties=media.name={LOOPBACK_MEDIA_NAME}",
            ],
            timeout=PACTL_LOAD_TIMEOUT,
        )
        return int(result.stdout.strip()) if result.ok and result.stdout.strip().isdigit() else None

    def _list_sources_short_fast(self) -> list[AudioSource]:
        result = self.runner.run(
            ["pactl", "list", "sources", "short"],
            timeout=PACTL_FAST_LIST_TIMEOUT,
        )
        if not result.ok:
            return []
        return parse_pactl_sources_short(result.stdout)

    def _list_sink_names_short_fast(self) -> set[str]:
        result = self.runner.run(
            ["pactl", "list", "sinks", "short"],
            timeout=PACTL_FAST_LIST_TIMEOUT,
        )
        if not result.ok:
            return set()
        return parse_pactl_names_short(result.stdout)

    def _list_modules_short_fast(self) -> list[AudioModule]:
        result = self.runner.run(
            ["pactl", "list", "modules", "short"],
            timeout=PACTL_FAST_LIST_TIMEOUT,
        )
        if not result.ok:
            return []
        return parse_pactl_modules_short(result.stdout)

    def _null_sink_module(self, modules: list[AudioModule]) -> AudioModule | None:
        return self._first_module(
            modules, "module-null-sink", [f"sink_name={SINK_NAME}"]
        )

    def _remap_module(self, modules: list[AudioModule]) -> AudioModule | None:
        needles = [f"source_name={MIC_NAME}", f"master={SINK_NAME}.monitor"]
        return self._first_module(
            modules, "module-remap-source", needles
        ) or self._first_module(modules, "module-virtual-source", needles)

    def _loopback_module(
        self, modules: list[AudioModule], *, source: str | None = None
    ) -> AudioModule | None:
        real_source = source or self.detect_real_source()
        needles = [f"sink={SINK_NAME}"]
        if real_source:
            needles.append(f"source={real_source}")
        return self._first_module(modules, "module-loopback", needles)

    @staticmethod
    def _first_module(
        modules: list[AudioModule], name: str, needles: list[str]
    ) -> AudioModule | None:
        for module in modules:
            if module.name == name and all(needle in module.args for needle in needles):
                return module
        return None

    def _load_module_state(self) -> ModuleState:
        if not self.paths.module_state_file.exists():
            return ModuleState()
        try:
            with self.paths.module_state_file.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                return ModuleState()
            field_names = {field.name for field in fields(ModuleState)}
            payload = {name: value[name] for name in field_names if name in value}
            return ModuleState(**payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return ModuleState()

    def _save_module_state(self, state: ModuleState) -> None:
        ensure_app_dirs(self.paths)
        with self.paths.module_state_file.open("w", encoding="utf-8") as handle:
            json.dump(asdict(state), handle, indent=2, sort_keys=True)
            handle.write("\n")

    @staticmethod
    def _store_module_id(
        state: ModuleState, field_name: str, module_id: int | None
    ) -> ModuleState:
        values = asdict(state)
        values[field_name] = module_id
        return ModuleState(**values)

    def _detect_real_source_from_sources(self, sources: list[AudioSource]) -> str | None:
        real_sources = [source for source in sources if source_is_real_mic(source.name)]
        names = {source.name for source in real_sources}
        if self.settings.selected_mic_source in names:
            return self.settings.selected_mic_source

        default_source = self.get_default_source()
        if default_source in names:
            return default_source

        return real_sources[0].name if real_sources else None

    @staticmethod
    def _description_for_name(devices: list[AudioSource], name: str | None) -> str | None:
        if name is None:
            return None
        for device in devices:
            if device.name == name:
                return device.description or device.name
        return name

    def _health_state(self, status: AudioStatus) -> str:
        if not status.pactl_available or not status.pipewire_available:
            return "unavailable"
        if status.last_error:
            return "error"
        if status.sink_exists and status.virtual_mic_exists:
            if not self.settings.mic_passthrough_enabled:
                return "ready"
            if status.selected_real_mic is None or status.loopback_exists:
                return "ready"
        return "needs_repair"

    @staticmethod
    def _with_error(status: AudioStatus, message: str) -> AudioStatus:
        return replace(status, last_error=message, state="error")
