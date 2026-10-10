from __future__ import annotations

import functools
import io
import math
import os
import struct
import wave
from pathlib import Path

from .safe_files import open_regular_file

BEEP_SAMPLE_RATE = 48000
BEEP_CHANNELS = 2
BEEP_FREQUENCY_HZ = 880.0
BEEP_SECONDS = 0.25
BEEP_AMPLITUDE = 0.4
BEEP_FADE_SECONDS = 0.01


def beep_frames() -> bytes:
    """Return a short sine beep as 48 kHz stereo s16le PCM.

    The format matches the low-latency mixer, so the beep plays without ffmpeg.
    Short fades avoid clicks at the start and end.
    """

    total = int(BEEP_SAMPLE_RATE * BEEP_SECONDS)
    fade = int(BEEP_SAMPLE_RATE * BEEP_FADE_SECONDS)
    frames = bytearray()
    for index in range(total):
        envelope = min(1.0, index / fade, (total - 1 - index) / fade)
        value = (
            BEEP_AMPLITUDE
            * envelope
            * math.sin(2 * math.pi * BEEP_FREQUENCY_HZ * index / BEEP_SAMPLE_RATE)
        )
        sample = int(value * 32767)
        frames += struct.pack("<hh", sample, sample)
    return bytes(frames)


@functools.cache
def beep_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(BEEP_CHANNELS)
        output.setsampwidth(2)
        output.setframerate(BEEP_SAMPLE_RATE)
        output.writeframes(beep_frames())
    return buffer.getvalue()


def write_beep_wav(path: Path, *, owner: tuple[int, int] | None = None) -> None:
    data = beep_wav_bytes()
    # Rewriting an identical beep would bump its mtime, which makes the mixer
    # decode and cache it again on every Test sound press.
    try:
        with open_regular_file(path, "rb") as existing:
            owned = owner is None or os.fstat(existing.fileno()).st_uid == owner[0]
            if owned and existing.read(len(data) + 1) == data:
                return
    except OSError:
        pass
    # Owned by the Steam user so the root-run mixer accepts it like a library sound.
    with open_regular_file(
        path,
        "wb",
        permissions=0o600,
        enforce_permissions=True,
        owner=owner,
    ) as handle:
        handle.write(data)
