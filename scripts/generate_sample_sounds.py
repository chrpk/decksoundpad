#!/usr/bin/env python3
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "defaults" / "sounds" / "sample"
SAMPLE_RATE = 22_050
AMPLITUDE = 0.35


def envelope(index: int, total: int) -> float:
    attack = max(1, int(total * 0.08))
    release = max(1, int(total * 0.22))
    if index < attack:
        return index / attack
    if index > total - release:
        return max(0.0, (total - index) / release)
    return 1.0


def tone(
    path: Path,
    duration: float,
    sample_fn: Callable[[float], float],
) -> None:
    frames = int(SAMPLE_RATE * duration)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        for index in range(frames):
            t = index / SAMPLE_RATE
            value = sample_fn(t) * envelope(index, frames) * AMPLITUDE
            packed = struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))
            handle.writeframesraw(packed)


def sine(freq: float, t: float) -> float:
    return math.sin(2 * math.pi * freq * t)


def main() -> int:
    random.seed(42)
    OUT.mkdir(parents=True, exist_ok=True)

    tone(
        OUT / "ready-chime.wav",
        0.48,
        lambda t: 0.65 * sine(660, t) + 0.35 * sine(990, t),
    )
    tone(
        OUT / "button-pop.wav",
        0.22,
        lambda t: sine(220 + 900 * t, t),
    )
    tone(
        OUT / "alert-ping.wav",
        0.35,
        lambda t: 0.55 * sine(880, t) + 0.45 * sine(1320, t),
    )
    tone(
        OUT / "error-buzz.wav",
        0.42,
        lambda t: 0.6 * sine(150, t) + 0.4 * sine(180, t),
    )
    tone(
        OUT / "soft-noise.wav",
        0.32,
        lambda _t: random.uniform(-0.55, 0.55),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
