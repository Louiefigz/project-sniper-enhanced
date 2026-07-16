#!/usr/bin/env python3
"""CLIPPER skill — normalize brain-authored keep ranges so the deterministic
renderer accepts them.

The brain decides WHICH spans to keep (editorial); this makes those spans
frame-safe (mechanical) so ``render_cut.py`` and ``clipper_fcpxml.ts`` render
without drift errors. It NEVER changes which content is kept — only the exact
frame boundaries.

Why it's needed: ASR (especially local whisper) emits word timestamps that can
overshoot the media's last frame. ``cut_speed`` predicts output length from the
ranges and hard-errors if the rendered timeline drifts, so a range that ends past
the source duration fails the render. This snaps each boundary to the frame grid,
clamps to ``[0, last_full_frame]``, drops empty/inverted ranges, and merges ranges
that touch after snapping.

    clipper_normalize_ranges.py <video> <raw_ranges.json> <clean_ranges.json>

ranges shape (in and out): [{"start": float, "end": float, "text": str}, ...]
"""

import json
import math
import subprocess
import sys


def probe(video: str) -> tuple[float, float]:
    """Return (fps, duration_seconds) from the first video stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate,duration:format=duration", "-of", "json", video],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    stream = (data.get("streams") or [{}])[0]
    num, _, den = (stream.get("r_frame_rate") or "30/1").partition("/")
    fps = (float(num) / float(den)) if den and float(den) else 30.0
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0.0)
    if duration <= 0:
        raise SystemExit("ffprobe returned no usable duration")
    return fps, duration


def normalize(ranges: list[dict], fps: float, duration: float) -> list[dict]:
    last_frame_s = (math.floor(duration * fps) - 1) / fps  # never past the last full frame
    snap = lambda t: round(t * fps) / fps
    clamp = lambda t: max(0.0, min(snap(t), last_frame_s))

    cleaned = []
    for r in ranges:
        start, end = clamp(float(r["start"])), clamp(float(r["end"]))
        if end - start < 1.0 / fps:           # drop empty / inverted after clamping
            continue
        cleaned.append({"start": start, "end": end, "text": str(r.get("text", "")).strip()})

    cleaned.sort(key=lambda r: r["start"])
    merged: list[dict] = []
    for r in cleaned:                          # merge ranges that touch after snapping
        if merged and r["start"] <= merged[-1]["end"] + 0.5 / fps:
            merged[-1]["end"] = max(merged[-1]["end"], r["end"])
            merged[-1]["text"] = (merged[-1]["text"] + " " + r["text"]).strip()
        else:
            merged.append(dict(r))
    return merged


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: clipper_normalize_ranges.py <video> <raw_ranges.json> <clean_ranges.json>",
              file=sys.stderr)
        return 1
    video, raw_path, out_path = sys.argv[1:4]
    fps, duration = probe(video)
    raw = json.load(open(raw_path))
    if not isinstance(raw, list) or not raw:
        print("raw_ranges.json must be a non-empty list of {start,end,text}", file=sys.stderr)
        return 1
    clean = normalize(raw, fps, duration)
    if not clean:
        print("no valid ranges after normalization (all empty or out of bounds)", file=sys.stderr)
        return 1
    json.dump(clean, open(out_path, "w"))
    kept = sum(r["end"] - r["start"] for r in clean)
    print(json.dumps({"ranges": len(clean), "keptSeconds": round(kept, 2),
                      "fps": fps, "sourceDuration": round(duration, 3)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
