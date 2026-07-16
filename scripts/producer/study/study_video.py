#!/usr/bin/env python3
"""study_video — the STUDY verb: fingerprint a reference short frame-by-frame.

The operator hands the system reference videos (example shorts they admire); the
system fingerprints each one so the editor brain can study pacing / graphics /
styles and write "rules of the road". This is the DETERMINISTIC extraction half
(pacing, unique visual states, audio profile, optional speech rate); the vision
review of each state — layout / graphics / caption classification — is brain-side
and driven by the report's checklist.

Reuses the FRAME.IO REVIEW frame/dedup machinery and the producer's own
face/screen/loudness analysers, so a "state" this tool surfaces is the same
state the QC + placement stages reason about. See
docs/producer/PRODUCER_MOTION_GRAPHICS_PLAN.md (the fingerprint feeds the doctrine loop).

CLI:
    study_video.py <video> <out_dir> [--fps 2] [--transcribe]
                   [--scdet-threshold 10] [--dedup-threshold 6]
Writes ``<out_dir>/fingerprint.json`` + ``<out_dir>/report.md`` and copies each
representative into ``<out_dir>/states/``. Prints NDJSON status lines to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_probe import first_stream, ffprobe_json  # noqa: E402
from study.study_audio import profile_audio  # noqa: E402
from study.study_cuts import compute_pacing, detect_cuts  # noqa: E402
from study.study_report import build_fingerprint, render_report  # noqa: E402
from study.study_states import analyze_states  # noqa: E402
from study.study_transcribe import transcribe_profile  # noqa: E402


def _emit(status: str, **fields) -> None:
    """One NDJSON status line on stdout (sibling-stage contract)."""
    print(json.dumps({"status": status, **fields}), flush=True)


def _probe(video_path: str) -> tuple[float, bool]:
    """(duration_s, has_audio) from a single ffprobe pass."""
    probe = ffprobe_json(video_path)
    try:
        duration = float(probe.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return duration, first_stream(probe, "audio") is not None


def study(video_path: str, out_dir: str, fps: float, do_transcribe: bool,
          scdet_threshold: float, dedup_threshold: int) -> dict:
    """Run the full deterministic fingerprint; write outputs; return it."""
    os.makedirs(out_dir, exist_ok=True)
    duration, has_audio = _probe(video_path)
    if duration <= 0:
        raise RuntimeError(f"cannot read duration for {video_path}")

    _emit("cuts", threshold=scdet_threshold)
    pacing = compute_pacing(detect_cuts(video_path, scdet_threshold), duration)
    _emit("states", fps=fps)
    states = analyze_states(video_path, out_dir, fps, dedup_threshold)
    _emit("audio", hasAudio=has_audio)
    audio = profile_audio(video_path, duration, has_audio)
    transcript = None
    if do_transcribe:
        _emit("transcribe")
        transcript = transcribe_profile(video_path)

    meta = {
        "video": os.path.abspath(video_path),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fps": fps, "threshold": dedup_threshold, "scdetThreshold": scdet_threshold,
    }
    fingerprint = build_fingerprint(meta, pacing, states, audio, transcript)
    report_md = render_report(fingerprint, pacing, states, audio, transcript)
    _write_outputs(out_dir, fingerprint, report_md)
    _emit("done", states=len(states), cuts=pacing.cut_count,
          cutsPerMin=pacing.cuts_per_min, longestStaticS=pacing.longest_static_s,
          music=audio.music.get("label"),
          fingerprint=os.path.join(out_dir, "fingerprint.json"),
          report=os.path.join(out_dir, "report.md"))
    return fingerprint


def _write_outputs(out_dir: str, fingerprint: dict, report_md: str) -> None:
    """Persist fingerprint.json + report.md side by side."""
    with open(os.path.join(out_dir, "fingerprint.json"), "w") as handle:
        json.dump(fingerprint, handle, indent=2)
    with open(os.path.join(out_dir, "report.md"), "w") as handle:
        handle.write(report_md)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="STUDY a reference video → fingerprint.json + report.md")
    parser.add_argument("video", help="reference video to fingerprint")
    parser.add_argument("out_dir", help="output directory for the fingerprint")
    parser.add_argument("--fps", type=float, default=2.0,
                        help="frame sampling rate for state detection (default 2)")
    parser.add_argument("--transcribe", action="store_true",
                        help="also transcribe (wpm + hook text); needs DEEPGRAM_API_KEY")
    parser.add_argument("--scdet-threshold", type=float, default=10.0,
                        help="scdet scene-cut score gate 0-100 (default 10)")
    parser.add_argument("--dedup-threshold", type=int, default=6,
                        help="pHash Hamming gate for state dedup (default 6)")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        _emit("error", error=f"not a file: {args.video}")
        return 1
    try:
        study(args.video, args.out_dir, args.fps, args.transcribe,
              args.scdet_threshold, args.dedup_threshold)
    except (OSError, RuntimeError, ValueError) as exc:
        _emit("error", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
