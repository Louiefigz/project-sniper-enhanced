"""Signal checks shared by Shorts and long-form delivery.

Speech-band active energy is neither LUFS nor semantic speech detection. Level
changes require editorial review, not automatic gain flattening. Channel faults
must be checked before any mono averaging or enhancement model can hide them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

from audit.audit_checks import CheckResult, FAIL, PASS, WARN

SAMPLE_RATE = 8000
BALANCE_FAIL_DB = 12.0
DEAD_CHANNEL_DBFS = -52.0
ACTIVE_CHANNEL_DBFS = -35.0
LEVEL_CHANGE_REVIEW_DB = 6.0
WINDOW_SAMPLES = SAMPLE_RATE // 10


@dataclass(frozen=True)
class ReviewSection:
    """An explicit interval on the final output clock, in seconds."""

    start: float
    end: float
    label: str


def _db(amplitude: np.ndarray) -> np.ndarray:
    """Convert nonnegative amplitude to finite dBFS with a numerical floor."""
    return 20.0 * np.log10(np.maximum(amplitude, 1e-12))


def _window_rms(samples: np.ndarray, size: int) -> np.ndarray:
    """Filter bounded slices, carrying state and including the final partial."""
    sos = signal.butter(4, [120.0, 3400.0], "bandpass", fs=SAMPLE_RATE, output="sos")
    state = np.zeros((len(sos), 2, 2))
    windows = []
    for start in range(0, len(samples), size):
        filtered, state = signal.sosfilt(sos, samples[start:start + size], axis=0, zi=state)
        if not np.all(np.isfinite(filtered)):
            raise ValueError("nonfinite filtered audio")
        scale = np.maximum(np.max(np.abs(filtered), axis=0), 1e-12)
        windows.append(scale * np.sqrt(np.mean(np.square(filtered / scale), axis=0)))
    return np.asarray(windows)


def _active(rms: np.ndarray) -> np.ndarray:
    """Retain the existing relative/absolute channel activity threshold."""
    maximum = _db(np.max(rms, axis=1))
    return maximum >= max(-48.0, float(np.max(maximum)) - 25.0)


def _global_balance(filtered: np.ndarray) -> CheckResult:
    """Keep whole-piece dead-channel and directional-median failure checks."""
    rms = _window_rms(filtered, SAMPLE_RATE // 2)
    active = _active(rms)
    if not np.any(active):
        return CheckResult("audio_channel_balance", FAIL, "no active dialogue", "")
    left, right = _db(np.sqrt(np.mean(np.square(rms[active]), axis=0)))
    deltas = _db(rms[active, 0]) - _db(rms[active, 1])
    delta = float(np.median(deltas))
    direction = max(float(np.mean(deltas > 0)), float(np.mean(deltas < 0)))
    dead = min(left, right) < DEAD_CHANNEL_DBFS and max(left, right) > ACTIVE_CHANNEL_DBFS
    severe = abs(delta) > BALANCE_FAIL_DB and direction >= 0.80
    measured = (f"L {left:.1f} / R {right:.1f} dBFS; median delta {delta:+.1f} dB, "
                f"direction {direction:.0%}")
    return CheckResult("audio_channel_balance", FAIL if dead or severe else PASS,
                       measured, f"fail if dead or >{BALANCE_FAIL_DB:.0f} dB consistently")


def _fault_runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Combine adjacent faulty windows without cancelling opposite directions."""
    edges = np.diff(np.r_[False, flags, False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def _interval_balance(filtered: np.ndarray) -> list[CheckResult]:
    """Expose brief or alternating ear failures hidden by global statistics."""
    rms = _window_rms(filtered, WINDOW_SAMPLES)
    levels = _db(rms)
    deltas = levels[:, 0] - levels[:, 1]
    dead = ((np.min(levels, axis=1) < DEAD_CHANNEL_DBFS)
            & (np.max(levels, axis=1) > ACTIVE_CHANNEL_DBFS))
    active = np.max(levels, axis=1) >= -48.0
    faulty = active & (dead | (np.abs(deltas) > BALANCE_FAIL_DB))
    rows = []
    for start, end in _fault_runs(faulty):
        lo, hi = start * WINDOW_SAMPLES, min(end * WINDOW_SAMPLES, len(filtered))
        measured = (f"{lo / SAMPLE_RATE:.3f}-{hi / SAMPLE_RATE:.3f}s; "
                    f"L-R {np.min(deltas[start:end]):+.1f}.."
                    f"{np.max(deltas[start:end]):+.1f} dB")
        rows.append(CheckResult(f"audio_channel_interval_{start:06d}", FAIL, measured,
                                "100 ms windows; dead channel or >12 dB imbalance"))
    if not rows:
        rows.append(CheckResult("audio_channel_intervals", PASS,
                                f"{len(rms)} windows including final partial", "100 ms analysis"))
    return rows


def _finite_number(value: object) -> bool:
    """Accept finite JSON numbers only; booleans and numeric strings are invalid."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


CLOCK_ROUNDING_TOLERANCE_S = 0.12   # ~3.5 frames at 30fps: encode rounding, not a defect


def _parse_section(item: object, duration: float) -> ReviewSection:
    """Validate one explicit, measurable output interval without coercion."""
    if not isinstance(item, dict):
        raise ValueError("each audioReviewSections item must be an object")
    start, end, label = item.get("start"), item.get("end"), item.get("label")
    if not (_finite_number(start) and _finite_number(end)):
        raise ValueError("section start/end must be finite numeric output seconds")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("section label must be a nonempty string")
    if not 0 <= start < end:
        raise ValueError(f"section {label!r} exceeds output duration or has invalid bounds")
    if end > duration:
        # The sections are the PLAN's clock; the file is its frame-quantised encode, so the
        # last section can end a few milliseconds past the decoded audio. Clamp that, and
        # only refuse an overshoot too large to be rounding.
        if end - duration > CLOCK_ROUNDING_TOLERANCE_S or start >= duration:
            raise ValueError(f"section {label!r} exceeds output duration or has invalid bounds")
        end = duration
    if round(end * SAMPLE_RATE) <= round(start * SAMPLE_RATE):
        raise ValueError(f"section {label!r} contains no analysis samples")
    return ReviewSection(float(start), float(end), label)


def _sections(plan: dict, duration: float) -> list[ReviewSection]:
    """Reject missing/ambiguous or overlapping review clocks rather than guessing."""
    items = plan.get("audioReviewSections")
    if not isinstance(items, list) or not items:
        raise ValueError("audioReviewSections must be a nonempty list")
    sections = [_parse_section(item, duration) for item in items]
    if any(after.start < before.end for before, after in zip(sections, sections[1:])):
        raise ValueError("audioReviewSections must be ordered and nonoverlapping")
    return sections


def _section_level(filtered: np.ndarray, section: ReviewSection) -> float | None:
    """Measure active speech-band energy; do not call this VAD or loudness."""
    audio = filtered[round(section.start * SAMPLE_RATE):round(section.end * SAMPLE_RATE)]
    rms = _window_rms(audio, WINDOW_SAMPLES)
    energy = np.mean(np.square(rms), axis=1)
    levels = _db(np.sqrt(energy))
    active = levels >= max(-60.0, float(np.max(levels)) - 25.0)
    if not np.any(active) or len(audio) < WINDOW_SAMPLES:
        return None
    return float(_db(np.asarray(np.sqrt(np.mean(energy[active])))))


def _level_results(filtered: np.ndarray, plan: dict) -> list[CheckResult]:
    """Report large adjacent energy changes for listening, preserving expression."""
    if "audioReviewSections" not in plan:
        return [CheckResult("audio_dialogue_consistency", WARN, "sections not supplied",
                            "explicit output intervals required; no cross-clip comparison")]
    try:
        sections = _sections(plan, len(filtered) / SAMPLE_RATE)
    except ValueError as error:
        return [CheckResult("audio_dialogue_consistency", FAIL, str(error), "invalid review clock")]
    levels = [_section_level(filtered, section) for section in sections]
    rows = [_level_row(section, level, index) for index, (section, level)
            in enumerate(zip(sections, levels))]
    for index in range(1, len(sections)):
        before, after = levels[index - 1], levels[index]
        if before is None or after is None or abs(after - before) < LEVEL_CHANGE_REVIEW_DB:
            continue
        measured = (f"{sections[index - 1].label!r} -> {sections[index].label!r} at "
                    f"{sections[index].start:.3f}s; {after - before:+.1f} dB "
                    f"({before:.1f} -> {after:.1f} dBFS active energy)")
        rows.append(CheckResult(f"audio_dialogue_level_change_{index:06d}", WARN, measured,
                                "review >=6 dB change; intentional whispers/emphasis may be valid"))
    status = WARN if any(row.status == WARN for row in rows) or len(sections) < 2 else PASS
    rows.insert(0, CheckResult("audio_dialogue_consistency", status,
                              f"{len(sections)} sections; {max(0, len(sections) - 1)} adjacent pairs",
                              "declared output intervals; 120-3400 Hz energy, not LUFS/VAD or spoken-sync proof"))
    return rows


def _level_row(section: ReviewSection, level: float | None, index: int) -> CheckResult:
    """Retain section measurements even when no change threshold is exceeded."""
    measured = f"{section.label!r} {section.start:.3f}-{section.end:.3f}s; "
    measured += "insufficient active energy" if level is None else f"{level:.1f} dBFS active energy"
    return CheckResult(f"audio_dialogue_section_{index:06d}", WARN if level is None else PASS,
                       measured, "signal energy only; includes any speech-band music/noise")


def check_dialogue_consistency(samples: np.ndarray, plan: dict) -> list[CheckResult]:
    """Check finite 8 kHz stereo audio and explicit output review sections.

    Args:
        samples: Decoded audio with shape (sample_count, 2) at 8 kHz.
        plan: Optional audioReviewSections list of start/end/label objects.

    Returns:
        Objective channel findings and section-energy review findings.
    """
    if (not isinstance(samples, np.ndarray) or samples.ndim != 2
            or samples.shape[1] != 2 or not len(samples)):
        return [CheckResult("audio_dialogue_samples", FAIL, "expected nonempty Nx2 audio", "8 kHz stereo")]
    numeric = np.issubdtype(samples.dtype, np.integer) or np.issubdtype(samples.dtype, np.floating)
    if not numeric or not np.all(np.isfinite(samples)):
        return [CheckResult("audio_dialogue_samples", FAIL, "nonfinite/nonnumeric audio", "cannot measure")]
    if not isinstance(plan, dict):
        return [CheckResult("audio_dialogue_consistency", FAIL, "plan must be an object", "invalid review clock")]
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            return [_global_balance(samples), *_interval_balance(samples), *_level_results(samples, plan)]
    except (ValueError, FloatingPointError) as error:
        return [CheckResult("audio_dialogue_samples", FAIL, str(error), "cannot measure")]
