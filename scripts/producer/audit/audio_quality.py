#!/usr/bin/env python3
"""Rendered-audio quality gates for Audit B.

The checks operate on the final mux, not intermediate intentions: stream timing,
dialogue-channel balance, persistent narrow-band hum, and the ending music mix.
Hum detection requires a stable spectral line, so ordinary broadband room noise
and normal low voice energy do not trip it.  The ending check is plan-gated and
reports signal-derived masking cues; it does not claim source separation.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from audit.audit_checks import CheckResult, FAIL, PASS, WARN  # noqa: E402
from audit.audit_probe import ffprobe_json, first_stream  # noqa: E402

SAMPLE_RATE = 8000
HUM_SAMPLE_RATE = 1000
SYNC_START_TOLERANCE_S = 0.080
SYNC_END_TOLERANCE_S = 0.120
BALANCE_FAIL_DB = 12.0
DEAD_CHANNEL_DBFS = -52.0
ACTIVE_CHANNEL_DBFS = -35.0
HUM_RANGE_HZ = (40.0, 240.0)
HUM_PROMINENCE_DB = 14.0
HUM_FRAME_PROMINENCE_DB = 10.0
HUM_MIN_LEVEL_DBFS = -48.0
HUM_MIN_RUN_S = 2.0
VOICE_FLOOR_DBFS = -44.0


@dataclass
class HumMetrics:
    """Measurements for the strongest stable low-frequency spectral line."""

    frequency_hz: float
    prominence_db: float
    level_dbfs: float
    coverage: float
    longest_run_s: float


@dataclass
class MixMetrics:
    """Ending/body cues used to estimate tonal or stereo masking of speech."""

    tonal_diffuse_db: float
    diffuse_dbfs: float
    total_dbfs: float
    side_mid_db: float


def _safe_float(value: object) -> Optional[float]:
    """Finite float or None for ffprobe's missing/N/A values."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stream_bounds(stream: Optional[dict]) -> Optional[tuple[float, float]]:
    """Return a stream's presentation start/end, deriving duration if needed."""
    if stream is None:
        return None
    start = _safe_float(stream.get("start_time")) or 0.0
    duration = _safe_float(stream.get("duration"))
    if duration is None:
        ticks = _safe_float(stream.get("duration_ts"))
        try:
            duration = ticks * float(Fraction(str(stream["time_base"]))) if ticks else None
        except (KeyError, ValueError, ZeroDivisionError):
            duration = None
    return None if duration is None else (start, start + duration)


def _timing_result(final_path: str) -> CheckResult:
    """Check both stream starts and ends, including any audio after picture."""
    probe = ffprobe_json(final_path)
    video = _stream_bounds(first_stream(probe, "video"))
    audio = _stream_bounds(first_stream(probe, "audio"))
    detail = (f"start <= {SYNC_START_TOLERANCE_S:.3f}s; "
              f"end <= {SYNC_END_TOLERANCE_S:.3f}s")
    if video is None or audio is None:
        return CheckResult("audio_av_timing", FAIL, "unmeasured streams", detail)
    start_skew, end_skew = audio[0] - video[0], audio[1] - video[1]
    ok = (abs(start_skew) <= SYNC_START_TOLERANCE_S
          and abs(end_skew) <= SYNC_END_TOLERANCE_S)
    tail = "post-picture audio" if end_skew > SYNC_END_TOLERANCE_S else "end skew"
    measured = (f"start {start_skew:+.3f}s; {tail} {end_skew:+.3f}s "
                f"(V {video[1] - video[0]:.3f}s / A {audio[1] - audio[0]:.3f}s)")
    return CheckResult("audio_av_timing", PASS if ok else FAIL, measured, detail)


def _decode_stereo(final_path: str) -> Optional[np.ndarray]:
    """Decode the final audio to compact 8 kHz float stereo for analysis."""
    cmd = ["ffmpeg", "-v", "error", "-i", final_path, "-map", "0:a:0",
           "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    raw = np.frombuffer(proc.stdout, dtype="<f4")
    return raw[: raw.size - raw.size % 2].reshape(-1, 2).astype(np.float64)


def _amp_db(value: float) -> float:
    """Amplitude/RMS to dBFS with a stable numerical floor."""
    return 20.0 * math.log10(max(float(value), 1e-12))


def _channel_result(samples: np.ndarray) -> CheckResult:
    """Detect one dead or consistently much quieter speech-band channel."""
    sos = signal.butter(4, [120.0, 3400.0], "bandpass", fs=SAMPLE_RATE,
                        output="sos")
    filtered = signal.sosfilt(sos, samples, axis=0)
    frame = SAMPLE_RATE // 2
    count = len(filtered) // frame
    if count < 1:
        return CheckResult("audio_channel_balance", WARN, "clip too short", "")
    windows = filtered[:count * frame].reshape(count, frame, 2)
    rms = np.sqrt(np.mean(np.square(windows), axis=1) + 1e-24)
    max_db = 20.0 * np.log10(np.max(rms, axis=1) + 1e-12)
    active = max_db >= max(-48.0, float(np.max(max_db)) - 25.0)
    if not np.any(active):
        return CheckResult("audio_channel_balance", FAIL, "no active dialogue", "")
    levels = np.sqrt(np.mean(np.square(rms[active]), axis=0))
    left_db, right_db = _amp_db(levels[0]), _amp_db(levels[1])
    deltas = 20.0 * np.log10((rms[active, 0] + 1e-12) /
                             (rms[active, 1] + 1e-12))
    delta = float(np.median(deltas))
    direction = max(float(np.mean(deltas > 0)), float(np.mean(deltas < 0)))
    dead = (min(left_db, right_db) < DEAD_CHANNEL_DBFS
            and max(left_db, right_db) > ACTIVE_CHANNEL_DBFS)
    severe = abs(delta) > BALANCE_FAIL_DB and direction >= 0.80
    measured = (f"L {left_db:.1f} / R {right_db:.1f} dBFS; "
                f"median delta {delta:+.1f} dB, direction {direction:.0%}")
    detail = f"fail if dead or >{BALANCE_FAIL_DB:.0f} dB consistently"
    return CheckResult("audio_channel_balance", FAIL if dead or severe else PASS,
                       measured, detail)


def _local_floor(magnitudes: np.ndarray, frequencies: np.ndarray,
                 index: int) -> np.ndarray:
    """Per-frame local spectral floor around one bin, excluding the line."""
    distance = np.abs(frequencies - frequencies[index])
    neighbors = (distance <= 12.0) & (distance >= 3.0)
    return np.median(magnitudes[neighbors], axis=0)


def _longest_run(flags: np.ndarray, hop_s: float) -> float:
    """Duration represented by the longest consecutive True run."""
    best = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        best = max(best, current)
    return best * hop_s


def _tone_metrics(magnitudes: np.ndarray, frequencies: np.ndarray,
                  index: int, hop_s: float) -> HumMetrics:
    """Measure persistence and strength for one fixed-frequency candidate."""
    floor = _local_floor(magnitudes, frequencies, index)
    frame_prom = 20.0 * np.log10((magnitudes[index] + 1e-12) / (floor + 1e-12))
    frame_level = 20.0 * np.log10(np.sqrt(2.0) * magnitudes[index] + 1e-12)
    stable = ((frame_prom >= HUM_FRAME_PROMINENCE_DB)
              & (frame_level >= HUM_MIN_LEVEL_DBFS))
    selected = stable if np.any(stable) else np.ones_like(stable, dtype=bool)
    return HumMetrics(float(frequencies[index]),
                      float(np.median(frame_prom[selected])),
                      float(np.median(frame_level[selected])),
                      float(np.mean(stable)), _longest_run(stable, hop_s))


def _hum_metrics(mono: np.ndarray) -> Optional[HumMetrics]:
    """Find any sustained fixed low-frequency line, including an ending-only hum."""
    if len(mono) < SAMPLE_RATE * 2:
        return None
    reduced = signal.resample_poly(mono, HUM_SAMPLE_RATE, SAMPLE_RATE)
    size = min(HUM_SAMPLE_RATE, len(reduced))
    overlap = size // 2
    frequencies, _, zxx = signal.stft(
        reduced, fs=HUM_SAMPLE_RATE, window="hann", nperseg=size, noverlap=overlap,
        boundary=None, padded=False)
    magnitudes = np.abs(zxx)
    band = np.flatnonzero((frequencies >= HUM_RANGE_HZ[0])
                          & (frequencies <= HUM_RANGE_HZ[1]))
    hop_s = (size - overlap) / HUM_SAMPLE_RATE
    candidates = [_tone_metrics(magnitudes, frequencies, int(index), hop_s)
                  for index in band]
    return max(candidates, key=lambda item: (item.longest_run_s,
                                             item.prominence_db))


def _hum_result(samples: np.ndarray) -> CheckResult:
    """Grade hum only when a narrow tone is strong, stable, and sustained."""
    metrics = _hum_metrics(np.mean(samples, axis=1))
    if metrics is None:
        return CheckResult("audio_tonal_hum", WARN, "clip too short to measure",
                           f"needs >= {HUM_MIN_RUN_S:.1f}s")
    bad = (metrics.prominence_db >= HUM_PROMINENCE_DB
           and metrics.longest_run_s >= HUM_MIN_RUN_S
           and metrics.level_dbfs >= HUM_MIN_LEVEL_DBFS)
    measured = (f"{metrics.frequency_hz:.1f} Hz; prominence "
                f"{metrics.prominence_db:.1f} dB; level {metrics.level_dbfs:.1f} "
                f"dBFS; stable {metrics.coverage:.0%}/{metrics.longest_run_s:.1f}s")
    detail = "stable narrow tone, not broadband low-frequency noise"
    return CheckResult("audio_tonal_hum", FAIL if bad else PASS, measured, detail)


def _mix_metrics(samples: np.ndarray) -> Optional[MixMetrics]:
    """Estimate tonal masking, diffuse voice energy, and stereo-side energy."""
    if len(samples) < 512:
        return None
    mid = np.mean(samples, axis=1)
    side = (samples[:, 0] - samples[:, 1]) / 2.0
    frequencies, _, zxx = signal.stft(
        mid, fs=SAMPLE_RATE, nperseg=512, noverlap=384,
        boundary=None, padded=False)
    power = np.abs(zxx[(frequencies >= 100) & (frequencies <= 3500)]) ** 2
    floor = signal.medfilt(power, kernel_size=(9, 1))
    floor = np.maximum(floor, np.percentile(power, 20, axis=0, keepdims=True))
    tonal = np.sum(np.maximum(power - 3.0 * floor, 0.0), axis=0)
    diffuse = np.sum(np.minimum(power, 3.0 * floor), axis=0)
    tonal_db = 10.0 * math.log10((float(np.median(tonal)) + 1e-15) /
                                 (float(np.median(diffuse)) + 1e-15))
    diffuse_db = 10.0 * math.log10(2.0 * float(np.median(diffuse)) + 1e-15)
    mid_db = _amp_db(float(np.sqrt(np.mean(np.square(mid)))))
    side_db = _amp_db(float(np.sqrt(np.mean(np.square(side)))))
    return MixMetrics(tonal_db, diffuse_db, mid_db, side_db - mid_db)


def _ending_result(samples: np.ndarray, plan: dict) -> CheckResult:
    """Fail a music-enabled ending whose bed masks or replaces active speech."""
    if not (plan.get("music") or {}).get("enabled"):
        return CheckResult("audio_ending_mix", PASS, "music disabled/not declared",
                           "ending dominance check not applicable")
    duration = len(samples) / SAMPLE_RATE
    window_s = min(3.0, max(1.5, duration * 0.25))
    window = int(window_s * SAMPLE_RATE)
    if len(samples) < window * 2:
        return CheckResult("audio_ending_mix", WARN, "clip too short to compare", "")
    body = _mix_metrics(samples[-2 * window:-window])
    ending = _mix_metrics(samples[-window:])
    if body is None or ending is None:
        return CheckResult("audio_ending_mix", WARN, "unmeasured ending", "")
    body_voice = body.diffuse_dbfs >= VOICE_FLOOR_DBFS
    end_voice = ending.diffuse_dbfs >= VOICE_FLOOR_DBFS
    tonal_jump = ending.tonal_diffuse_db - body.tonal_diffuse_db
    side_jump = ending.side_mid_db - body.side_mid_db
    masks_voice = end_voice and (
        (ending.tonal_diffuse_db > 3.0 and tonal_jump > 5.0)
        or (ending.side_mid_db > -6.0 and side_jump > 5.0))
    bed_only = (body_voice and not end_voice and ending.total_dbfs > -40.0
                and (ending.tonal_diffuse_db > 0.0 or ending.side_mid_db > -12.0))
    measured = (f"end tonal/diffuse {ending.tonal_diffuse_db:+.1f} dB "
                f"(body {body.tonal_diffuse_db:+.1f}); voice floor "
                f"{ending.diffuse_dbfs:.1f} dBFS; side/mid {ending.side_mid_db:+.1f} dB")
    detail = "music must remain behind voice; no stereo-bed-only tail"
    return CheckResult("audio_ending_mix", FAIL if masks_voice or bed_only else PASS,
                       measured, detail)


def check_audio_quality(final_path: str, plan: dict) -> list[CheckResult]:
    """Run objective rendered-audio QC and return Audit B ``CheckResult`` rows."""
    results = [_timing_result(final_path)]
    samples = _decode_stereo(final_path)
    if samples is None or not len(samples):
        results.append(CheckResult("audio_quality_decode", FAIL,
                                   "no decodable audio", ""))
        return results
    results.extend([_channel_result(samples), _hum_result(samples),
                    _ending_result(samples, plan)])
    return results
