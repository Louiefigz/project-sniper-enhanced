"""Deterministic non-speech calibration bed for the explicit full-body TEST.

Seeded broadband energy avoids the historical fixture's persistent140Hz line.
It is NOT voice, room-noise remediation, ASR evidence or listening approval.
The real hum/peak/loudness gates are unchanged and still judge encoded output.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Callable

import numpy as np
from scipy import signal

RATE = 48000
SEED = 720907
MAX_DURATION_S = 360.0
CHUNK_SAMPLES = RATE


def _block(rng: np.random.Generator, state: tuple, span: tuple[int, int]) -> tuple:
    """Continuous filter state and absolute modulation clock across fixed chunks."""
    sos, previous = state
    start, count = span
    raw = rng.uniform(-1.0, 1.0, count)
    filtered, following = signal.sosfilt(sos, raw, zi=previous)
    seconds = (start + np.arange(count)) / RATE
    envelope = 0.65 + 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * 2.7 * seconds)) ** 2
    samples = filtered * envelope * 0.65
    if not np.isfinite(samples).all() or np.max(np.abs(samples)) >= 0.98:
        raise RuntimeError("TEST calibration bed exceeded its finite unclipped sample class")
    return np.rint(samples * 32767).astype("<i2").tobytes(), following


def write_calibration_bed(path: Path, duration: float,
                          guard: Callable[[], None] = lambda: None) -> None:
    """Write a bounded new PCM16 file; preserve partial output on any failure."""
    if type(duration) not in (int, float) or not math.isfinite(duration) \
            or not 0 < duration <= MAX_DURATION_S:
        raise ValueError("TEST calibration duration must be positive and at most360s")
    count = round(duration * RATE)
    rng = np.random.default_rng(SEED)
    sos = signal.butter(4, [120, 3200], "bandpass", fs=RATE, output="sos")
    state = np.zeros((sos.shape[0], 2))
    guard()
    with path.open("xb") as target, wave.open(target, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        for start in range(0, count, CHUNK_SAMPLES):
            guard()
            block, state = _block(rng, (sos, state), (start, min(CHUNK_SAMPLES, count - start)))
            handle.writeframesraw(block)
        guard()
