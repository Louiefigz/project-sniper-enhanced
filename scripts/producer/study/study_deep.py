#!/usr/bin/env python3
"""study_deep — the DETERMINISTIC deep extractor for reference videos.

Where study_video fingerprints a reference (pacing / states / audio), this
digs out the EDIT MECHANICS frame by frame — every measurable fact comes from
pixels, audio and arithmetic; agents are reserved for the opt-in semantics
micro-layer. Six passes, one canonical ``deep_study.json``
(schema: study/DEEP_SCHEMA.md):

P1 fingerprint   — reuse study_video's outputs (run it if absent).
P2 motion        — per-frame d-metric, Haar face track (x + width = zoom
                   proxy), phase-correlation pan, dark/bright fractions,
                   freeze (YDIF==0) runs.                (deep_signals)
P3 events        — impulses + runs + region POP SCAN → cut (scdet-anchored,
                   faceW punch)/zoom/pan/panel/graphic/freeze/flash with
                   bbox, duration, magnitude, transition class
                   (hard-cut/sweep/fade/flash/pop) + active-span easing;
                   co-occurring moves separated per region. (deep_events)
P4 text          — tesseract OCR per graphic event + state, colours,
                   per-word timing, caption-system stats.  (deep_text/_captions)
P5 word lock     — every event's distance to the nearest word boundary,
                   via the producer's own word_lock arithmetic; words from
                   --transcript (JSON or .vtt) or a sibling .vtt
                   auto-discovered next to the video.     (deep_wordlock)
P6 semantics     — OPT-IN (--semantics): schema-forced per-event agent
                   micro-tasks; the core pipeline runs with zero AI.

CLI: study_deep.py <video> <out_dir> [--fps N] [--meticulous] [--semantics]
                   [--transcript words.json|captions.vtt] [--skip-captions]
                   [--text-scope all|states]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_captions import caption_stats  # noqa: E402
from study.deep_classify import ClassifyCtx  # noqa: E402
from study.deep_events import detect_events  # noqa: E402
from study.deep_frames import probe_video  # noqa: E402
from study.deep_semantics import run_semantics  # noqa: E402
from study.deep_signals import collect_signals, freeze_runs  # noqa: E402
from study.deep_text import graphics_text, require_tesseract, states_text  # noqa: E402
from study.deep_wordlock import load_words, word_lock_stats  # noqa: E402
from study.study_transcribe import (add_asr_arguments, invocation_from_options,  # noqa: E402
                                    use_asr_invocation)

MAX_DEFAULT_FPS = 30.0     # native-fps analysis, capped (60fps doubles cost)


def _emit(status: str, **fields) -> None:
    """One NDJSON status line on stdout (sibling-stage contract)."""
    print(json.dumps({"status": status, **fields}), flush=True)


def _fingerprint(video: str, out_dir: str) -> dict:
    """P1: load the study_video fingerprint, running the study if absent."""
    path = os.path.join(out_dir, "fingerprint.json")
    if not os.path.isfile(path):
        from study.study_video import study
        study(video, out_dir, fps=2.0, do_transcribe=False,
              scdet_threshold=10.0, dedup_threshold=6)
    with open(path) as handle:
        return json.load(handle)


def _text_pass(video: str, info, job: tuple,
               opts: argparse.Namespace) -> dict:
    """P4: graphics OCR + state OCR + caption stats."""
    scope = getattr(opts, "text_scope", "all")
    if scope not in ("all", "states"):
        raise ValueError("text_scope must be all or states")
    require_tesseract()
    events, fingerprint = job
    text = {"graphics": graphics_text(video, info, events, opts.eff_fps) if scope == "all" else [],
            "states": states_text(fingerprint)}
    if scope == "states":
        text["graphicsSkipped"] = "--text-scope states; per-event OCR timing is unmeasured"
    text["captions"] = ({"detected": False, "skipped": "--skip-captions"}
                        if opts.skip_captions else caption_stats(video, info))
    return text


def _study_params(opts: argparse.Namespace) -> dict:
    """Record the extraction scope alongside its sampling configuration."""
    return {"fps": opts.eff_fps, "semantics": bool(opts.semantics),
            "meticulous": bool(getattr(opts, "meticulous", False)),
            "textScope": getattr(opts, "text_scope", "all")}


def run_deep(opts: argparse.Namespace) -> dict:
    """All passes in order; writes and returns the canonical deep study."""
    os.makedirs(opts.out_dir, exist_ok=True)
    info = probe_video(opts.video)
    meticulous = bool(getattr(opts, "meticulous", False))
    opts.eff_fps = opts.fps or (info.fps if meticulous
                                else min(info.fps, MAX_DEFAULT_FPS))
    _emit("fingerprint")
    fingerprint_path = os.path.join(opts.out_dir, "fingerprint.json")
    fingerprint = _fingerprint(opts.video, opts.out_dir)
    _emit("signals", fps=opts.eff_fps)
    sig = collect_signals(opts.video, info, opts.eff_fps)
    from study.study_cuts import detect_cuts
    scdet_cuts = [c.time for c in detect_cuts(opts.video)]
    _emit("events", frames=sig.frames, scdetCuts=len(scdet_cuts))
    detected = detect_events(ClassifyCtx(opts.video, info, sig),
                             scdet_cuts=scdet_cuts)
    _emit("text", events=len(detected["events"]))
    text = _text_pass(opts.video, info, (detected["events"], fingerprint), opts)
    _emit("wordlock")
    words, meta = load_words(opts.video, opts.out_dir, opts.transcript)
    word_lock = word_lock_stats(detected["events"], words, meta)
    semantics = {"ran": False}
    if opts.semantics:
        _emit("semantics")
        semantics = run_semantics(opts.video, info, detected["events"],
                                  opts.out_dir)
    deep = {
        "video": os.path.abspath(opts.video),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": _study_params(opts),
        "source": {"width": info.width, "height": info.height,
                   "fps": info.fps, "durationS": info.duration},
        "fingerprint": {"path": fingerprint_path},
        "signals": sig.to_json(),
        "freezes": freeze_runs(sig),
        "events": detected["events"], "unclassifiedRuns": detected["unclassifiedRuns"],
        "text": text,
        "wordLock": word_lock,
        "semantics": semantics,
    }
    out_path = os.path.join(opts.out_dir, "deep_study.json")
    with open(out_path, "w") as handle:
        json.dump(deep, handle, indent=2)
    _emit("done", events=len(deep["events"]),
          unclassifiedRuns=deep["unclassifiedRuns"],
          graphicsWithText=len(text["graphics"]),
          captions=text["captions"].get("detected"),
          deepStudy=out_path)
    return deep


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DEEP-STUDY a reference video → deep_study.json")
    parser.add_argument("video", help="reference video to extract")
    parser.add_argument("out_dir", help="study output directory")
    parser.add_argument("--fps", type=float, default=None,
                        help="analysis fps (default: native, capped at 30)")
    parser.add_argument("--meticulous", action="store_true",
                        help="analyze every source-cadence frame without the 30fps cap")
    parser.add_argument("--semantics", action="store_true",
                        help="OPT-IN agent micro-layer (claude -p per graphic)")
    parser.add_argument("--transcript", default=None,
                        help="word-timing JSON or YouTube-style .vtt (skips "
                             "any transcription; with neither given, a "
                             "sibling <stem>*.vtt is auto-discovered)")
    parser.add_argument("--skip-captions", action="store_true",
                        help="skip the full-video caption OCR sampling pass")
    parser.add_argument("--text-scope", choices=("all", "states"), default="all",
                        help="states reads every visual state but skips repeated per-event OCR; "
                             "all motion events and transcript word-lock remain measured")
    add_asr_arguments(parser)
    opts = parser.parse_args()

    if not os.path.isfile(opts.video):
        _emit("error", error=f"not a file: {opts.video}")
        return 1
    try:
        require_tesseract()  # P4 always reads on-screen text: refuse before P1-P3 work, not after
        with use_asr_invocation(invocation_from_options(opts)):
            run_deep(opts)
    except (OSError, RuntimeError, ValueError) as exc:
        _emit("error", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
