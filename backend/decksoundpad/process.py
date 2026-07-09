from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def decky_runtime_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    original_runtime_dir = env.get("XDG_RUNTIME_DIR")
    runtime_dir = _select_audio_runtime_dir(env)
    env["XDG_RUNTIME_DIR"] = runtime_dir
    if (
        "DBUS_SESSION_BUS_ADDRESS" not in env
        or (
            original_runtime_dir is not None
            and original_runtime_dir != runtime_dir
            and original_runtime_dir in env["DBUS_SESSION_BUS_ADDRESS"]
        )
    ):
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"
    env.setdefault("PULSE_SERVER", f"unix:{runtime_dir}/pulse/native")
    return env


def _select_audio_runtime_dir(env: Mapping[str, str]) -> str:
    candidates = _runtime_dir_candidates(env)
    # Audio commands must talk to the Steam user's Pulse socket, not the root
    # runtime that Decky may inherit when the plugin has elevated permissions.
    for runtime_dir in candidates:
        if (Path(runtime_dir) / "pulse" / "native").exists():
            return runtime_dir
    for runtime_dir in candidates:
        if Path(runtime_dir).exists():
            return runtime_dir
    return candidates[0]


def _runtime_dir_candidates(env: Mapping[str, str]) -> list[str]:
    candidates: list[str] = []

    def add(runtime_dir: str | None) -> None:
        if runtime_dir and runtime_dir not in candidates:
            candidates.append(runtime_dir)

    add(env.get("XDG_RUNTIME_DIR"))
    for key in ("SUDO_UID", "PKEXEC_UID"):
        uid = _numeric_uid(env.get(key))
        if uid is not None:
            add(f"/run/user/{uid}")

    # Decky exposes the target user's home more reliably than a UID in some
    # launch paths; stat it to recover the matching /run/user/<uid> directory.
    decky_user_home = env.get("DECKY_USER_HOME")
    if decky_user_home:
        try:
            add(f"/run/user/{Path(decky_user_home).stat().st_uid}")
        except OSError:
            pass

    add(f"/run/user/{os.getuid()}")

    run_user = Path("/run/user")
    try:
        entries = sorted(
            run_user.iterdir(),
            key=lambda path: (path.name == "0", path.name),
        )
    except OSError:
        entries = []
    for entry in entries:
        if entry.is_dir() and entry.name.isdigit():
            add(str(entry))

    return candidates or [f"/run/user/{os.getuid()}"]


def _numeric_uid(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)


def run_capture(
    args: Sequence[str],
    *,
    timeout: float = 5.0,
    env: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> RunResult:
    try:
        completed = subprocess.run(
            list(args),
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=dict(env) if env is not None else None,
            **subprocess_user_kwargs(user_home),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        timeout_msg = f"timeout after {timeout:.1f}s: {' '.join(map(str, args))}"
        stderr = f"{stderr}\n{timeout_msg}".strip()
        return RunResult(124, stdout, stderr)
    return RunResult(completed.returncode, completed.stdout, completed.stderr)


def subprocess_user_kwargs(user_home: Path | None) -> dict[str, object]:
    """Return Popen options that drop a root child to the Steam user."""

    if user_home is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return {}
    try:
        home_stat = user_home.stat()
        if home_stat.st_uid == 0:
            raise RuntimeError("refusing to launch an audio subprocess as root")
        username = pwd.getpwuid(home_stat.st_uid).pw_name
        groups = os.getgrouplist(username, home_stat.st_gid)
    except (KeyError, OSError) as exc:
        raise RuntimeError("could not resolve the Steam user for subprocess launch") from exc
    return {
        "user": home_stat.st_uid,
        "group": home_stat.st_gid,
        "extra_groups": groups,
    }
