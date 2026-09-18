#!/usr/bin/env python3
"""speech_cleanup — one-shot cutTrack from a raw take (the UI's cleanup button).

Wraps the EXISTING edit brains in one deterministic call: ``pause_scan``
proposes which inter-sentence gaps to tighten, ``retake_scan`` proposes which
re-taken spans to drop, and ``apply_pauses.cut_track_from_pauses`` folds both
(plus the abandoned cold-open rule) into a clean cutTrack. Nothing is
reimplemented here — this is only the wiring + the CLI contract.

Doctrine guard: retakes flagged ``needsOperator`` (long-range block matches /
earlier-candidate verdicts) are SKIPPED by default — never auto-cut a minute
of footage on fuzzy evidence. ``--all-retakes`` folds them too (operator
reviewed the proposal).

Output: NDJSON progress events, then one final line
``{"status": "done", "cutTrack": [...], "segments": N, "removedS": X.X}``.

CLI: speech_cleanup.py <manifest.json> [--source-id ID] [--out cutTrack.json]
       [--all-retakes]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path

import retake_scan
from edit import pause_scan
from edit.apply_pauses import cut_track_from_pauses, removed_seconds


def emit(event: str, **fields) -> None:
    """Emit one NDJSON status line to stdout (worker convention)."""
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


def resolve_source(manifest_path: str, source_id: str | None) -> dict:
    """Pick the manifest source (default: first) and absolutize its transcript.

    Raises ``ValueError`` on an unknown source id or a missing transcript —
    fail loudly, never guess (no fallback matching).
    """
    with open(manifest_path) as f:
        manifest = json.load(f)
    sources = manifest.get("sources") or []
    if not sources:
        raise ValueError(f"manifest {manifest_path} has no sources")
    if source_id is None:
        src = sources[0]
    else:
        by_id = {s["id"]: s for s in sources}
        if source_id not in by_id:
            raise ValueError(f"sourceId {source_id!r} not in manifest "
                             f"(have: {sorted(by_id)})")
        src = by_id[source_id]
    transcript = src.get("transcriptPath")
    if not transcript:
        raise ValueError(f"source {src['id']!r} has no transcriptPath")
    if not os.path.isabs(transcript):
        transcript = os.path.join(os.path.dirname(os.path.abspath(manifest_path)),
                                  transcript)
    if not os.path.isfile(transcript):
        raise ValueError(f"transcript not found: {transcript}")
    return {"id": src["id"], "duration": float(src["duration"]),
            "transcript": transcript}


def build_cut_track(src: dict, all_retakes: bool) -> dict:
    """pause_scan + retake_scan → folded cutTrack for the whole source window."""
    pauses = pause_scan.scan(src["transcript"])
    emit("pause_scan", proposedTrimCount=pauses["proposedTrimCount"],
         proposedTrimTotalS=pauses["proposedTrimTotalS"],
         protectedCount=pauses["protectedCount"])
    retake_report = retake_scan.analyze(src["transcript"])
    retakes = retake_report["retakes"]
    applied = retakes if all_retakes else [r for r in retakes
                                           if not r["needsOperator"]]
    emit("retake_scan", retakeCount=len(retakes), applied=len(applied),
         skippedNeedsOperator=len(retakes) - len(applied))
    window = (0.0, src["duration"])
    track = cut_track_from_pauses(pauses, src["id"], window,
                                  retakes=applied)
    return {"cutTrack": track, "segments": len(track),
            "removedS": removed_seconds(track, window),
            "skippedRetakes": len(retakes) - len(applied)}


def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot speech-cleanup cutTrack "
                                 "(pauses + retakes + cold-open drop).")
    ap.add_argument("manifest")
    ap.add_argument("--source-id", help="manifest source id (default: first)")
    ap.add_argument("--out", help="write {cutTrack, segments, removedS} here")
    ap.add_argument("--all-retakes", action="store_true",
                    help="also fold needsOperator retakes (operator reviewed)")
    args = ap.parse_args()
    try:
        # The WHOLE flow lives in the try: a malformed transcript (or a bad
        # --out path) must end in a final {"status": "error"} NDJSON line —
        # never a raw traceback with no status line (the UI contract).
        src = resolve_source(args.manifest, args.source_id)
        emit("source", sourceId=src["id"], durationS=src["duration"],
             transcript=src["transcript"])
        result = build_cut_track(src, args.all_retakes)
        if args.out:
            with open(args.out, "w") as f:
                json.dump(result, f, indent=1)
    except (OSError, json.JSONDecodeError, KeyError, ValueError,
            TypeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), flush=True)
        return 1
    print(json.dumps({"status": "done", **result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
