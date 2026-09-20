#!/usr/bin/env python3
"""apply_pauses — fold pause_scan trims into a silence-cut cutTrack.

pause_scan PROPOSES which inter-word gaps to tighten (each down to a kept breath
``residual_s``); its doctrine says "the brain folds the trims into the cut
track." This is that fold, made deterministic: given the proposal + a content
window, it emits the ``cutTrack`` segments that KEEP the content (and each gap's
breath) and DROP the removed silence between them. Protected pauses are kept
whole (never trimmed). This is the missing wire between the edit brain
(pause_scan) and the renderer (cut_speed), so a produced short is actually
tightened instead of rendering raw dead air.

A gap trim ``{at_s, gap_s, residual_s}`` means: keep up to ``at_s + residual_s``
(the breath), then resume at ``at_s + gap_s`` (past the removed silence). The
window's own bounds are the first/last segment edges.

``--media`` makes every pause drop SAFE: whisper's word starts can be late (a word
whose audio has already begun is timestamped 0.1s later), so a transcript gap can
contain the first moment of the next word — and cutting it deletes speech. With the
source media, each pause drop is intersected with silence MEASURED in that audio, so
a pause cut can only ever remove audio that was actually silent. Retake drops are
content decisions and are not clamped.

CLI:
    apply_pauses.py <pauses.json> --source raw-1 --window START END
        [--media SOURCE.mov] [--speed S] [--out cuttrack.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

MIN_SEG_S = 0.05                  # drop degenerate slivers
LEAD_FRAGMENT_S = 1.6             # a leading kept span this short, orphaned before
LEAD_DROP_S = 2.0                 # a drop this large, is an abandoned cold-open


def measured_silence(media_path: str) -> list[tuple[float, float]]:
    """Silence intervals measured in ``media_path`` (empty when unmeasurable)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))                    # scripts/ — shared modules
    from local_whisper_speech_edges import SpeechEdgeError, measure_silences
    try:
        return measure_silences(media_path)
    except SpeechEdgeError:
        return []


def _measured_drops(gap: tuple[float, float], residual: float,
                    silence: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """What to remove from one proposed pause, from the silence measured in the audio.

    The transcript's own gap bounds are unreliable in both directions — whisper pads word
    ends and starts words late — so the measured silence, not the gap, decides the cut:
    every measured span the gap touches is removed except ``residual`` seconds of breath
    at its start. A gap that touches no measured silence is not cut at all.
    """
    start, end = gap
    drops = []
    for span_start, span_end in silence:
        if min(end, span_end) - max(start, span_start) <= 0:
            continue
        cut_start = span_start + residual
        if span_end > cut_start:
            drops.append((cut_start, span_end))
    return drops


@dataclass
class CutOptions:
    """What the fold needs beyond the proposal and the window."""

    speed: float = 1.0
    retakes: list[dict] | None = None
    #: Silence measured in the source audio; pause cuts are clamped to it.
    silence: list[tuple[float, float]] | None = None


def cut_track_from_pauses(proposal: dict, source_id: str, window: tuple[float, float],
                          options: CutOptions | None = None) -> list[dict]:
    """Clean-cut cutTrack for ``[window]`` from the edit brain's proposals.

    Drops two kinds of source span and keeps the rest as content segments: the
    dead air pause_scan flagged (each gap minus its kept breath; protected pauses
    survive) AND — when ``retakes`` (retake_scan ``proposedTrims``/``retakes``) is
    given — every re-taken take's ``[cutStartS, cutEndS]`` span, so a false-start
    opening is removed instead of stitched onto the clean take. Overlapping drops
    merge. Returns ``[{sourceId, start, end, speed}]`` in time order."""
    options = options or CutOptions()
    speed = options.speed
    w0, w1 = window
    segs: list[dict] = []
    cursor = w0
    for start, end in _drop_intervals(proposal, options.retakes, window, options.silence):
        if start > cursor:
            segs.append(_seg(source_id, cursor, start, speed))
        cursor = max(cursor, end)
        if cursor >= w1:
            break
    if cursor < w1:
        segs.append(_seg(source_id, cursor, w1, speed))
    segs = [s for s in segs if s["end"] - s["start"] > MIN_SEG_S]
    return _drop_lead_fragment(segs)


def _drop_lead_fragment(segs: list[dict]) -> list[dict]:
    """Drop an abandoned cold-open: a very short first segment cut off from the
    take by a large drop (the C0679 "If …" — one word, then a 5s settle pause and
    a re-take). Conservative: only a ``≤ LEAD_FRAGMENT_S`` lead separated from the
    next segment by ``≥ LEAD_DROP_S`` of removed material, so a deliberate short
    cold-open that flows straight into the take is never touched."""
    while len(segs) >= 2:
        first, nxt = segs[0], segs[1]
        if (first["end"] - first["start"] <= LEAD_FRAGMENT_S
                and nxt["start"] - first["end"] >= LEAD_DROP_S):
            segs = segs[1:]
        else:
            break
    return segs


def _drop_intervals(proposal: dict, retakes: list[dict] | None,
                    window: tuple[float, float],
                    silence: list[tuple[float, float]] | None = None
                    ) -> list[tuple[float, float]]:
    """Merged, time-ordered source spans to DROP inside ``window`` — pause silence
    (gap past the kept breath) + whole retake cut spans, clamped to the window."""
    w0, w1 = window
    drops: list[tuple[float, float]] = []
    for t in proposal.get("proposedTrims", []):
        if t.get("protected"):
            continue
        at_s = float(t["at_s"])
        residual = float(t.get("residual_s", 0.0))
        if silence is None:
            start, end = max(at_s + residual, w0), min(at_s + float(t["gap_s"]), w1)
            if end > start:
                drops.append((start, end))
            continue
        # a pause cut removes measured silence, and all of it but the breath
        for start, end in _measured_drops((at_s, at_s + float(t["gap_s"])), residual, silence):
            start, end = max(start, w0), min(end, w1)
            if end > start:
                drops.append((start, end))
    for r in retakes or []:
        start = max(float(r["cutStartS"]), w0)
        end = min(float(r["cutEndS"]), w1)
        if end > start:
            drops.append((start, end))
    merged: list[tuple[float, float]] = []
    for start, end in sorted(drops):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _seg(source_id: str, start: float, end: float, speed: float) -> dict:
    return {"sourceId": source_id, "start": round(start, 3),
            "end": round(end, 3), "speed": speed}


def removed_seconds(cut_track: list[dict], window: tuple[float, float]) -> float:
    """How much the cut removed — silence + retakes (window span minus kept)."""
    kept = sum(s["end"] - s["start"] for s in cut_track)
    return round((window[1] - window[0]) - kept, 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pauses")
    ap.add_argument("--source", required=True)
    ap.add_argument("--window", nargs=2, type=float, required=True,
                    metavar=("START", "END"))
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--media", help="the source media: pause cuts are then clamped to "
                    "silence measured in it, so a late word start is never cut into")
    ap.add_argument("--retakes", help="retake_scan proposal JSON — also drop its "
                    "cut spans (false starts / re-takes)")
    ap.add_argument("--out")
    a = ap.parse_args()
    with open(a.pauses) as f:
        proposal = json.load(f)
    retakes = None
    if a.retakes:
        with open(a.retakes) as f:
            retakes = json.load(f).get("retakes", [])
    window = (a.window[0], a.window[1])
    silence = measured_silence(a.media) if a.media else None
    track = cut_track_from_pauses(proposal, a.source, window,
                                  CutOptions(a.speed, retakes, silence))
    out = {"cutTrack": track,
           "removedS": removed_seconds(track, window),
           "segments": len(track),
           "pauseCutsClampedToMeasuredSilence": silence is not None,
           "silenceSpansMeasured": len(silence) if silence is not None else None}
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "cutTrack"}))


if __name__ == "__main__":
    main()
