"""Measure retained silence on the kept clock, with transcript-only fallback.

Whisper's previous completed word is not a speech endpoint when its next word
straddles a boundary admitted by measured silence. Use the shared acoustic
measurement in that case, and count only quiet audio the edit actually keeps.
"""
from __future__ import annotations

import math

from transcript_cut_evidence import SourceEvidence
from local_whisper_speech_edges import Measurement

MAX_SEAM_SILENCE_S = 0.75
BOUNDARY_EPS_S = 0.015


def _quiet_ranges(source: SourceEvidence) -> list[tuple[float, float]] | None:
    """Intersect hysteresis runs with the shared conservative frame-level rule."""
    if source.silence_gate_dbfs is None or not source.frame_levels:
        return None
    measurement = Measurement(source.silence, source.frame_levels,
                              source.silence_gate_dbfs, source.frame_s)
    return [(max(start, left), min(end, right))
            for start, end in measurement.quiet_spans()
            for left, right in source.silence
            if max(start, left) < min(end, right)]


def _measured_edge(bounds: tuple[float, float], edge: str,
                   quiet: list[tuple[float, float]]) -> float:
    """Return the continuous measured quiet retained at one clip edge."""
    start, end = bounds
    at = start if edge == "start" else end
    for left, right in quiet:
        if left - 1e-9 <= at <= right + 1e-9:
            return max(0.0, min(end, right) - start if edge == "start"
                       else end - max(start, left))
    return 0.0


def _transcript_edge(at: float, edge: str, receipt: dict) -> float:
    """Retain the historical conservative rule when audio cannot be measured."""
    word = receipt["after" if edge == "start" else "before"]
    if word is None:
        return math.inf
    return max(0.0, word["start"] - at if edge == "start" else at - word["end"])


def inspect_retained(cut: dict, source: SourceEvidence,
                     seam: dict, errors: list[str]) -> None:
    """Attach evidence and enforce the same limit on each retained boundary."""
    start, end = float(cut["start"]), float(cut["end"])
    quiet = _quiet_ranges(source)
    measured = quiet is not None
    try:
        speed = float(cut.get("speed", 1))
    except (ValueError, TypeError):
        speed = math.nan
    if not math.isfinite(speed) or speed <= 0:
        errors.append(f"cutTrack[{seam['cutIndex']}]: speed must be finite and positive")
        speed = 1.0
    seam["outputDurationS"] = (end - start) / speed
    for edge, at in (("start", start), ("end", end)):
        silence = (_measured_edge((start, end), edge, quiet) if measured
                   else _transcript_edge(at, edge, seam[edge])) / speed
        seam[edge].update(retainedSilenceS=round(silence, 6) if math.isfinite(silence) else None,
                          silenceEvidence="measured-audio" if measured else "transcript")
        external = at <= BOUNDARY_EPS_S if edge == "start" else at >= source.duration - BOUNDARY_EPS_S
        if not external and silence > MAX_SEAM_SILENCE_S + 1e-9:
            evidence = "measured retained silence" if measured else "gap to its nearest kept word"
            errors.append(f"cutTrack[{seam['cutIndex']}]: {edge} has {silence:.3f}s "
                          f"{evidence} (max {MAX_SEAM_SILENCE_S}s)")


def inspect_joined(seams: list[dict], errors: list[str]) -> None:
    """Prevent several individually short quiet clips from hiding one long seam."""
    trailing = 0.0
    previous_index: int | None = None
    for seam in seams:
        start, end = seam["start"], seam["end"]
        if start.get("silenceEvidence") != "measured-audio":
            trailing, previous_index = 0.0, None
            continue
        leading, duration = start["retainedSilenceS"], seam["outputDurationS"]
        joined = trailing + leading
        if previous_index is not None and trailing > 0 and leading > 0 \
                and joined > MAX_SEAM_SILENCE_S + 1e-9:
            errors.append(f"cutTrack[{seam['cutIndex']}]: joined seam after "
                          f"cutTrack[{previous_index}] retains {joined:.3f}s measured silence "
                          f"(max {MAX_SEAM_SILENCE_S}s)")
        seam["joinedLeadingSilenceS"] = joined if previous_index is not None else leading
        trailing = joined if leading >= duration - 1e-9 else end["retainedSilenceS"]
        previous_index = seam["cutIndex"]
