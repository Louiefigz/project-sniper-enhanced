#!/usr/bin/env python3
"""audio_gain — per-section dialogue-bus gain (MG-2 ``audioGain`` track).

Applies a plan's ``audioGain`` track — ``[{"outStart", "outEnd", "dB"}]`` windows
in OUTPUT time — to a media file's audio via chained ffmpeg ``volume`` filters
(see docs/producer/PRODUCER_PLAN.md §4.5 "Per-section audio adjustments").

**Pipeline order matters.** In the renderer this runs on the DIALOGUE BUS BEFORE
ducking and BEFORE the two-pass loudnorm in ``master.py`` / ``audio_mix.py``.
loudnorm re-measures the whole program, so it keeps the delivery at -14 LUFS
while these windows only shift levels RELATIVE to one another (e.g. lift a quiet
answer, tuck a loud laugh). Applying gain AFTER loudnorm would defeat the
normalization; applying it here is the correct, documented order.

**Edge ramps (honest note).** A hard gain step at a window boundary is an audible
click / level jump. Each window is therefore an equal-slope trapezoid envelope
built straight into the ``volume`` expression: it ramps 1→gain over the first
``RAMP_S`` (50 ms) of the window, holds at gain, then ramps gain→1 over the last
``RAMP_S``. The multiplier is EXACTLY 1 outside ``[outStart, outEnd]``, so
chaining one filter per window is safe as long as windows do not overlap (which
is validated). Windows shorter than ``2*RAMP_S`` get a triangular envelope that
peaks at the target gain at their center (still smooth, never a hard step).

**Video is never re-encoded** (``-c:v copy``); only the audio stream is rebuilt
(AAC per ``producer_config.ENCODE``), so the output's video stream is
bit-identical to the input's (verified by md5 in the module self-check).

CLI: audio_gain.py <video_in> <gains.json> <video_out>
  gains.json = [{"outStart": s, "outEnd": e, "dB": +/-N}, ...]  (dB in [-12, +12])
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from producer_config import ENCODE
from audio.master import has_audio

RAMP_S = 0.05                  # 50 ms edge ramp (trapezoid envelope; §4.5)
DB_MIN, DB_MAX = -12.0, 12.0   # per-window gain bounds (validated, hard error)


@dataclass
class GainWindow:
    """One output-time gain window (kept to <=4 fields)."""

    out_start: float
    out_end: float
    db: float


def emit(event: str, **fields) -> None:
    """Emit one NDJSON status line to stdout (worker convention)."""
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _f(value: float) -> str:
    """Fixed-point float for an ffmpeg expression (no sci-notation)."""
    return f"{value:.6f}"


def _db_to_linear(db: float) -> float:
    """Convert a dB gain to a linear amplitude multiplier (10^(dB/20))."""
    return 10.0 ** (db / 20.0)


def parse_windows(raw: object) -> list[GainWindow]:
    """Validate the raw gains list into ``GainWindow`` objects.

    Raises ``ValueError`` on a non-list, a malformed entry, a non-numeric field,
    ``outEnd <= outStart``, or a ``dB`` outside ``[DB_MIN, DB_MAX]``.
    """
    if not isinstance(raw, list):
        raise ValueError("gains must be a JSON list of {outStart, outEnd, dB}")
    windows: list[GainWindow] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"gain[{i}] must be an object")
        try:
            values = [item[key] for key in ("outStart", "outEnd", "dB")]
            if any(type(value) not in (int, float) for value in values):
                raise ValueError("window fields must be JSON numbers")
            start, end, db = map(float, values)
            if not all(math.isfinite(value) for value in (start, end, db)):
                raise ValueError("window fields must be finite")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"gain[{i}] needs numeric outStart/outEnd/dB: {exc}") from exc
        if end <= start:
            raise ValueError(f"gain[{i}] outEnd ({end}) must exceed outStart ({start})")
        if not DB_MIN <= db <= DB_MAX:
            raise ValueError(f"gain[{i}] dB {db} outside [{DB_MIN}, {DB_MAX}]")
        windows.append(GainWindow(out_start=start, out_end=end, db=db))
    return windows


def overlap_error(windows: list[GainWindow]) -> Optional[str]:
    """Return an error string if any two windows overlap, else ``None``.

    Windows are checked in time order; touching at a shared edge
    (``a.end == b.start``) is allowed — only a true overlap is rejected.
    """
    ordered = sorted(windows, key=lambda w: w.out_start)
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.out_start < prev.out_end:
            return (f"windows overlap: [{prev.out_start}, {prev.out_end}] and "
                    f"[{cur.out_start}, {cur.out_end}]")
    return None


def _window_expr(w: GainWindow) -> str:
    """Trapezoid ``volume`` expression for one window (1 outside, gain inside).

    ``env`` is a 0..1 trapezoid: it rises across the first ``r`` of the window,
    holds at 1, and falls across the last ``r``; it is 0 everywhere outside
    ``[out_start, out_end]``. ``vol = 1 + (gain-1)*env`` therefore passes audio
    through untouched outside the window and lands at ``gain`` on the plateau.
    """
    gain = _db_to_linear(w.db)
    ramp = min(RAMP_S, (w.out_end - w.out_start) / 2.0)
    s, e, r, g = _f(w.out_start), _f(w.out_end), _f(ramp), _f(gain)
    env = f"min(clip((t-{s})/{r},0,1),clip(({e}-t)/{r},0,1))"
    return f"1+({g}-1)*{env}"


def build_filter(windows: list[GainWindow]) -> str:
    """Chain one time-evaluated ``volume`` filter per window.

    Each expression is single-quoted so its internal commas/parens are protected
    from the filtergraph's top-level comma separators.
    """
    return ",".join(f"volume=eval=frame:volume='{_window_expr(w)}'" for w in windows)


def apply_gain(video_in: str, windows: list[GainWindow], video_out: str) -> dict:
    """Apply the gain windows to ``video_in``'s audio → ``video_out``.

    Copies the video stream (bit-identical) and rebuilds only the audio stream.
    Returns a status dict; does not raise on ffmpeg failure (reports it).
    """
    afilter = build_filter(windows)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_in,
           "-map", "0:v:0", "-c:v", "copy",
           "-map", "0:a:0", "-af", afilter,
           "-c:a", ENCODE["acodec"], "-b:a", ENCODE["audio_bitrate"],
           "-ar", str(ENCODE["audio_rate"]), "-ac", str(ENCODE["audio_channels"]),
           "-movflags", ENCODE["movflags"], video_out]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(video_out)
    return {"ok": ok, "filter": afilter, "stderr": "" if ok else res.stderr[-800:]}


def run_audio_gain(video_in: str, gains_path: str, video_out: str) -> dict:
    """Load + validate the gains file and apply it. Returns a status dict."""
    if not has_audio(video_in):
        return {"status": "error", "error": "input has no audio stream to gain"}
    try:
        with open(gains_path) as fh:
            raw = json.load(fh)
        windows = parse_windows(raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}
    if not windows:
        return {"status": "error", "error": "no gain windows in file"}
    overlap = overlap_error(windows)
    if overlap:
        return {"status": "error", "error": overlap}
    result = apply_gain(video_in, windows, video_out)
    if not result["ok"]:
        return {"status": "error", "error": "ffmpeg gain pass failed",
                "detail": result["stderr"]}
    return {
        "status": "done",
        "out": video_out,
        "windows": [{"outStart": w.out_start, "outEnd": w.out_end, "dB": w.db}
                    for w in windows],
        "ramp_s": RAMP_S,
        "filter": result["filter"],
    }


def main() -> None:
    args = sys.argv[1:]
    if len(args) != 3:
        emit("error", error="Usage: audio_gain.py <video_in> <gains.json> <video_out>")
        sys.exit(1)
    status = run_audio_gain(args[0], args[1], args[2])
    emit("result", **status)
    sys.exit(0 if status.get("status") == "done" else 1)


if __name__ == "__main__":
    main()
