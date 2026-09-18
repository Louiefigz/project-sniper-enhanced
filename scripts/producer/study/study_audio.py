#!/usr/bin/env python3
"""study_audio — audio fingerprint for the STUDY verb (loudness / silence / music).

The editor brain studies not just what a reference short shows but how it
*sounds*: does the loudness breathe or sit flat under a bed, how much of the
runtime is silence, and is there music under the voice? All measured with the
same ffmpeg analysers the master/QC stages already trust:

  * loudness curve — ``ebur128`` momentary loudness (400ms window) sampled once
    per second (parsed from ``ametadata=print`` — the per-frame log lines are
    unreliable across ffmpeg builds, the metadata sidecar is stable).
  * silence ratio — ``silencedetect`` intervals summed over the runtime.
  * music-presence — a HEURISTIC, not a classifier (stated honestly). True
    speech-vs-music separation needs a trained model; instead we read three
    cheap, defensible proxies and combine them into a labelled guess with its
    reasons: (1) the loudness FLOOR (p10 of the momentary curve) — a music bed
    keeps the gaps between words elevated, speech-only drops to the noise floor;
    (2) the silence ratio — a bed suppresses detectable silence; (3) the crest
    factor from ``astats`` — heavily-mastered music compresses peaks toward RMS.

Raw measurement + one clearly-labelled heuristic. No pass/fail here.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_probe import measure_loudness, run_ff  # noqa: E402

# ametadata sidecar lines: "frame:5 pts:.. pts_time:0.5" then "lavfi.r128.M=-13.7"
_PTS_RE = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_M_RE = re.compile(r"lavfi\.r128\.M=(-?\d+(?:\.\d+)?|nan|inf|-inf)")
_SILENCE_DUR_RE = re.compile(r"silence_duration:\s*(\d+(?:\.\d+)?)")
_CREST_RE = re.compile(r"Crest factor:\s*(-?\d+(?:\.\d+)?)")
_RMS_RE = re.compile(r"RMS level dB:\s*(-?\d+(?:\.\d+)?)")

SILENCE_NOISE_DB = "-30dB"    # silencedetect amplitude gate
SILENCE_MIN_DUR = 0.35         # a gap shorter than this isn't counted as silence
# Music-heuristic decision lines (honest, calibrated on real shorts 2026-07-05).
MUSIC_FLOOR_LUFS = -45.0       # momentary floor above this ⇒ gaps stay lit (bed)
MUSIC_MAX_SILENCE_RATIO = 0.06 # a bed suppresses detectable silence below this
MUSIC_MAX_CREST = 11.0         # mastered music compresses crest below this dB


@dataclass
class AudioProfile:
    """The full audio fingerprint of one reference video."""

    has_audio: bool
    duration: float
    integrated_lufs: float | None
    true_peak_dbtp: float | None
    loudness_floor_lufs: float | None   # p10 of the momentary curve
    loudness_p50_lufs: float | None
    silence_ratio: float                # fraction of runtime detected silent
    silence_gaps: int
    crest_factor: float | None
    rms_level_db: float | None
    music: dict = field(default_factory=dict)     # {label, confidence, reasons[]}
    curve: list[dict] = field(default_factory=list)   # [{"t","m"}] per second


def _ff_output(cmd: list[str]) -> str:
    """Combined stderr+stdout of an ffmpeg run (ebur128/silencedetect/astats log
    to stderr; the ebur128 metadata print goes to stdout). Reuses run_ff."""
    proc = run_ff(cmd)
    return proc.stderr + proc.stdout


def loudness_curve(video_path: str) -> list[dict]:
    """Momentary loudness (LUFS) sampled once per second across the runtime.

    Parses the ``ebur128`` metadata sidecar; each integer second keeps the
    loudest momentary reading seen within it (the perceived level of that beat).
    Silence-floor readings (<= -120 LUFS) pass through so the floor is visible.
    """
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
         "-af", "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file=-",
         "-f", "null", "-"])
    per_sec: dict[int, float] = {}
    pending_t: float | None = None
    for line in out.splitlines():
        pts = _PTS_RE.search(line)
        if pts:
            pending_t = float(pts.group(1))
            continue
        m = _M_RE.search(line)
        if m and pending_t is not None:
            raw = m.group(1)
            if raw in ("nan", "inf", "-inf"):
                pending_t = None
                continue
            sec = int(pending_t)
            val = float(raw)
            per_sec[sec] = max(per_sec.get(sec, -1e9), val)
            pending_t = None
    return [{"t": s, "m": round(per_sec[s], 2)} for s in sorted(per_sec)]


def silence_stats(video_path: str, duration: float) -> tuple[float, int]:
    """(silence_ratio, gap_count) from ``silencedetect`` over the runtime."""
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
         "-af", f"silencedetect=noise={SILENCE_NOISE_DB}:d={SILENCE_MIN_DUR}",
         "-f", "null", "-"])
    durs = [float(x) for x in _SILENCE_DUR_RE.findall(out)]
    total = sum(durs)
    ratio = round(total / duration, 4) if duration > 0 else 0.0
    return min(ratio, 1.0), len(durs)


def astats_summary(video_path: str) -> tuple[float | None, float | None]:
    """(crest_factor_dB, rms_level_dB) from a single mono ``astats`` pass."""
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
         "-af", "aformat=channel_layouts=mono,astats=metadata=0", "-f", "null", "-"])
    crest = _CREST_RE.findall(out)
    rms = _RMS_RE.findall(out)
    return (float(crest[-1]) if crest else None,
            float(rms[-1]) if rms else None)


def _percentile(sorted_vals: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile of a sorted list, or None if empty."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(rank)
    if low + 1 >= len(sorted_vals):
        return round(sorted_vals[-1], 2)
    frac = rank - low
    return round(sorted_vals[low] + frac * (sorted_vals[low + 1] - sorted_vals[low]), 2)


def music_heuristic(floor: float | None, silence_ratio: float,
                    crest: float | None) -> dict:
    """Combine three proxies into a labelled music-presence guess + reasons.

    Honest limits: this is a heuristic, NOT a trained speech/music classifier.
    It reads sustained-energy signals; a slow ambient bed or a spoken-word track
    over silence can fool it. Reported with its evidence so the brain can weigh
    it, never as ground truth.
    """
    reasons: list[str] = []
    votes = 0
    if floor is not None and floor >= MUSIC_FLOOR_LUFS:
        votes += 1
        reasons.append(f"loudness floor {floor:.1f} LUFS >= {MUSIC_FLOOR_LUFS} "
                       "(gaps stay lit — bed likely)")
    elif floor is not None:
        reasons.append(f"loudness floor {floor:.1f} LUFS drops to noise "
                       "(speech-only pattern)")
    if silence_ratio <= MUSIC_MAX_SILENCE_RATIO:
        votes += 1
        reasons.append(f"silence ratio {silence_ratio:.3f} <= "
                       f"{MUSIC_MAX_SILENCE_RATIO} (little true silence)")
    if crest is not None and crest <= MUSIC_MAX_CREST:
        votes += 1
        reasons.append(f"crest factor {crest:.1f} dB <= {MUSIC_MAX_CREST} "
                       "(compressed — mastered-music-like)")
    elif crest is not None:
        reasons.append(f"crest factor {crest:.1f} dB (dynamic — speech-like)")
    label = "likely" if votes >= 2 else "unlikely" if votes == 0 else "uncertain"
    confidence = "low" if votes == 1 else "medium"
    return {"label": label, "confidence": confidence, "votes": votes,
            "reasons": reasons, "heuristic": True}


def profile_audio(video_path: str, duration: float, has_audio: bool) -> AudioProfile:
    """Assemble the full audio fingerprint (empty profile when no audio track)."""
    if not has_audio:
        return AudioProfile(False, round(duration, 3), None, None, None, None,
                            0.0, 0, None, None,
                            music={"label": "none", "confidence": "high",
                                   "reasons": ["no audio stream"], "heuristic": True})
    curve = loudness_curve(video_path)
    vals = sorted(pt["m"] for pt in curve if pt["m"] > -120.0)
    floor = _percentile(vals, 10)
    median = _percentile(vals, 50)
    silence_ratio, gaps = silence_stats(video_path, duration)
    crest, rms = astats_summary(video_path)
    lufs, peak = measure_loudness(video_path)
    return AudioProfile(
        has_audio=True, duration=round(duration, 3),
        integrated_lufs=lufs, true_peak_dbtp=peak,
        loudness_floor_lufs=floor, loudness_p50_lufs=median,
        silence_ratio=silence_ratio, silence_gaps=gaps,
        crest_factor=round(crest, 2) if crest is not None else None,
        rms_level_db=round(rms, 2) if rms is not None else None,
        music=music_heuristic(floor, silence_ratio, crest), curve=curve)
