#!/usr/bin/env python3
"""render_cut — the standalone CLIPPER→MP4 quick win.

Takes a single source + CLIPPER-style keep ranges (``computeFinalClips`` shape:
``[{"start", "end", "text"}]``) and renders a finished master: stage-1 cut+speed
(no reframe, no captions — longform semantics) into a mezzanine, then a final
H.264 High / AAC encode with two-pass loudnorm to −14 LUFS / −1.5 dBTP at the
source's own resolution and 16:9.

Composition only — all the frame-accurate cutting/normalizing lives in
:mod:`cut_speed`; every render number comes from :mod:`producer_config`.

CLI:
    render_cut.py <source.mp4> <keep_ranges.json> <out.mp4> [--speed 1.0]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cut_speed import (Profile, decide_profile, emit, probe_duration,  # noqa: E402
                       render_cut_speed, run_ff)
from producer_config import AUDIO, ENCODE  # noqa: E402

# libx264 entropy coder: H.264 High uses CABAC.
_CODER = {"cabac": "ac", "cavlc": "vlc"}
# loudnorm pass-1 measurement fields consumed by the pass-2 linear normalize.
_LN_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


def build_single_source_plan(source: str, ranges: list[dict], speed: float
                             ) -> tuple[dict, dict]:
    """Minimal in-memory longform plan + manifest for one source (no reframe /
    captions). Longform mode = cut time out, keep 16:9, burn nothing."""
    cut_track = [{"sourceId": "src", "start": float(r["start"]),
                  "end": float(r["end"]), "speed": speed} for r in ranges]
    plan = {"planVersion": 1, "target": {"mode": "longform"}, "cutTrack": cut_track}
    manifest = {"sources": [{"id": "src", "path": os.path.abspath(source),
                             "duration": probe_duration(source)}],
                "broll": [], "music": []}
    return plan, manifest


def measure_loudnorm(path: str) -> dict | None:
    """Pass 1 of two-pass loudnorm: measure integrated loudness / true peak /
    LRA / threshold on the mezzanine. Returns None if the print_format=json
    block is missing or non-finite (e.g. near-silent audio) so the caller falls
    back to single-pass dynamic loudnorm rather than feeding it garbage."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af",
         f"loudnorm=I={AUDIO['lufs_target']}:TP={-abs(AUDIO['true_peak_dbtp'])}:"
         f"LRA={AUDIO['lra']}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        vals = {k: float(data[k]) for k in _LN_KEYS}
    except (ValueError, KeyError):
        return None
    if any(v != v or abs(v) == float("inf") for v in vals.values()):
        return None
    return vals


def _loudnorm_af(measured: dict | None) -> str:
    """Build the loudnorm filter: linear two-pass when measured, else dynamic."""
    base = (f"loudnorm=I={AUDIO['lufs_target']}:"
            f"TP={-abs(AUDIO['true_peak_dbtp'])}:LRA={AUDIO['lra']}")
    if measured is None:
        return base
    return (f"{base}:measured_I={measured['input_i']}:"
            f"measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}:linear=true")


def _bitrate_for_fps(fps: float) -> str:
    """ENCODE.bitrate_by_fps has 30/60 anchors; pick by the high-fps threshold."""
    return ENCODE["bitrate_by_fps"][60] if fps > 45 else ENCODE["bitrate_by_fps"][30]


def _scale_bitrate(bitrate: str, factor: int) -> str:
    """'12M' -> factor× as an ffmpeg bitrate string (unit preserved)."""
    return f"{int(bitrate[:-1]) * factor}{bitrate[-1]}"


def master_encode(mezz: str, out_path: str, profile: Profile,
                  measured: dict | None) -> None:
    """Pass 2: encode the mezzanine to the delivery master — H.264 High, closed
    GOP, CABAC, faststart, CFR — applying the loudnorm to the audio."""
    bitrate = _bitrate_for_fps(float(profile.fps))
    flags = "+cgop" if ENCODE["gop_closed"] else "-cgop"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", mezz,
           "-c:v", ENCODE["vcodec"], "-profile:v", ENCODE["profile"],
           "-pix_fmt", ENCODE["pix_fmt"], "-preset", "medium",
           "-b:v", bitrate, "-maxrate", bitrate,
           "-bufsize", _scale_bitrate(bitrate, 2),
           "-bf", str(ENCODE["bframes"]), "-coder", _CODER[ENCODE["coder"]],
           "-flags", flags, "-fps_mode", "cfr", "-r", profile.fps_arg,
           "-af", _loudnorm_af(measured),
           "-ar", str(ENCODE["audio_rate"]), "-ac", str(ENCODE["audio_channels"]),
           "-c:a", ENCODE["acodec"], "-b:a", ENCODE["audio_bitrate"],
           "-movflags", ENCODE["movflags"], out_path]
    run_ff(cmd)


def render_cut(source: str, ranges_path: str, out_path: str, speed: float) -> dict:
    """Cut+speed the source then master it with two-pass loudnorm. Owns a temp
    work dir for the intermediate mezzanine (cleaned on exit)."""
    with open(ranges_path) as f:
        ranges = json.load(f)
    if not isinstance(ranges, list) or not ranges:
        raise RuntimeError("keep_ranges.json must be a non-empty list of {start,end}")
    work_dir = tempfile.mkdtemp(prefix="producer-rendercut-")
    try:
        plan, manifest = build_single_source_plan(source, ranges, speed)
        profile = decide_profile(source)
        mezz = os.path.join(work_dir, "mezzanine.mp4")
        render_cut_speed(plan, manifest, mezz, work_dir)
        emit(stage="render_cut", status="loudnorm_measure")
        measured = measure_loudnorm(mezz)
        if measured is None:
            emit(stage="render_cut", status="warn", reason="loudnorm_dynamic_fallback")
        master_encode(mezz, out_path, profile, measured)
        result = {"output": out_path,
                  "outputDuration": round(probe_duration(out_path), 4),
                  "ranges": len(ranges), "speed": speed,
                  "loudnorm": "two_pass" if measured else "dynamic"}
        emit(stage="render_cut", status="done", **result)
        return result
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER quick win: CLIPPER keep ranges → master MP4")
    ap.add_argument("source")
    ap.add_argument("keep_ranges")
    ap.add_argument("out")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()
    try:
        render_cut(args.source, args.keep_ranges, args.out, args.speed)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
