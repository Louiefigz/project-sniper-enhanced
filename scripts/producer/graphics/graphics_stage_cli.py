"""Existing ordinary graphics command; internal owned hooks have no CLI flags."""
from __future__ import annotations

import argparse
import json
import sys

from graphics.graphics_stage import GraphicsJob, run_graphics_stage
from graphics.stage_placement import emit


def arguments() -> argparse.Namespace:
    """Parse the unchanged public rendering options, not executable callbacks."""
    parser = argparse.ArgumentParser(description="PRODUCER MG stage: graphics compositing")
    parser.add_argument("video_in")
    parser.add_argument("track_path", help="the plan's graphicsTrack array (JSON)")
    parser.add_argument("video_out")
    parser.add_argument("--cache-dir", default=None,
                        help="content-hash render cache (default: templates/motion/renders/cache)")
    parser.add_argument("--ass", dest="ass_in", default=None,
                        help="burned-caption ASS to filter under own-screen takeovers")
    parser.add_argument("--ass-out", dest="ass_out", default=None,
                        help="where the filtered ASS is written (required with --ass)")
    parser.add_argument("--placements-out", default=None,
                        help="write the eye-trace placements sidecar here (Audit B)")
    parser.add_argument("--occlusions", default=None,
                        help="JSON file {broll:[[s,e]..], cards:[[s,e]..]} for verify")
    parser.add_argument("--producer-dir", default=None,
                        help="producer directory owning geometry/calibration evidence")
    parser.add_argument("--band-y-offset", type=float, default=0.0,
                        help="plan captions.bandYOffsetPx")
    result = parser.parse_args()
    if bool(result.ass_in) != bool(result.ass_out):
        parser.error("--ass and --ass-out must be given together")
    return result


def _read(path: str) -> object:
    """Read ordinary caller data using the existing JSON command semantics."""
    with open(path) as handle:
        return json.load(handle)


def main() -> None:
    """Execute ordinary graphics and retain its existing JSON status/errors."""
    args = arguments()
    try:
        job = GraphicsJob(video_in=args.video_in, video_out=args.video_out,
            track=_read(args.track_path), cache_dir=args.cache_dir,
            ass_in=args.ass_in, ass_out=args.ass_out, placements_out=args.placements_out,
            occlusions=_read(args.occlusions) if args.occlusions else None,
            producer_dir=args.producer_dir, band_y_offset_px=args.band_y_offset)
        emit(status="done", **run_graphics_stage(job))
    except (OSError, json.JSONDecodeError, KeyError, ValueError, RuntimeError) as exc:
        emit(error=str(exc))
        sys.exit(1)
