from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence

from .security import redact_token


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
    uid = os.getuid()
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir}/bus")
    return env


def run_capture(
    args: Sequence[str],
    *,
    timeout: float = 5.0,
    env: Mapping[str, str] | None = None,
) -> RunResult:
    try:
        completed = subprocess.run(
            list(args),
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=dict(env) if env is not None else None,
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


def sanitize_command(args: Sequence[str], *, token: str | None = None) -> list[str]:
    return [redact_token(str(arg), token) for arg in args]
