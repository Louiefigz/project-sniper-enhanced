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
MIN_DROP_S = 0.05                 # and never declare a removal shorter than one
LEAD_FRAGMENT_S = 1.6             # a leading kept span this short, orphaned before
LEAD_DROP_S = 2.0                 # a drop this large, is an abandoned cold-open


def _require_declared_media(media_path: str, manifest_path: str, source_id: str) -> None:
    """Refuse a --media that is not the file the manifest records for ``source_id``.

    Measuring one recording and cutting another produces cut points with no relation to
    the audio, and the receipt would still say they were clamped to measured silence.
    """
    with open(manifest_path) as handle:
        sources = json.load(handle).get("sources") or []
    declared = next((s.get("path") for s in sources if str(s.get("id")) == source_id), None)
    if declared is None:
        raise SystemExit(f"apply_pauses: the manifest has no source {source_id!r}")
    if os.path.realpath(declared) != os.path.realpath(media_path):
        raise SystemExit(
            f"apply_pauses: --media is not the media the manifest records for {source_id!r}.\n"
            f"  manifest: {declared}\n  --media : {media_path}")


def _measurement(media_path: str):
    """The shared audio measurement for ``media_path`` (cached for one run)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))                    # scripts/ — shared modules
    from local_whisper_speech_edges import SpeechEdgeError, measure
    global _MEASUREMENT
    if _MEASUREMENT is None:
        try:
            _MEASUREMENT = measure(media_path)
        except SpeechEdgeError as exc:
            raise SystemExit(f"apply_pauses: --media could not be measured: {exc}")
    return _MEASUREMENT


_MEASUREMENT = None


def measured_silence(media_path: str) -> list[tuple[float, float]]:
    """Silence intervals measured in ``media_path``.

    Raises:
        SystemExit: The audio could not be measured. An unmeasurable file must not read
            as "no silence here" — that is indistinguishable from a take with no pauses,
            and the receipt would still claim the cuts were clamped to measurement.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))                    # scripts/ — shared modules
    # The confidently-quiet runs, not the hysteresis spans: a cut may only remove audio
    # the cut gate will also clear as unspoken.
    return _measurement(media_path).quiet_spans()


def _measured_drops(gap: tuple[float, float], residual: float,
                    silence: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """What to remove from one proposed pause: measured silence, INSIDE the approved gap.

    The cut may never exceed what the brain proposed. An earlier version removed each
    touched span whole, on the reasoning that a transcript gap understates the real pause;
    one measured span covering two gaps then removed both — including a protected emphasis
    beat between them — turning a 0.25s approved trim into a 4.38s cut. The proposal is the
    authority on WHAT may go; the measurement only narrows it to what is really silent.
    """
    start, end = gap
    drops = []
    for span_start, span_end in silence:
        cut_start = max(span_start, start) + residual
        cut_end = min(span_end, end)
        if cut_end > cut_start:
            drops.append((cut_start, cut_end))
    return drops


def _protected_spans(proposal: dict) -> list[tuple[float, float]]:
    """Beats the brain marked KEEP — no cut may touch them, whatever the audio measures."""
    spans = []
    for trim in [*proposal.get("protectedPauses", []), *proposal.get("proposedTrims", [])]:
        if not trim.get("protected"):
            continue
        at_s = float(trim["at_s"])
        spans.append((at_s, at_s + float(trim["gap_s"])))
    return spans


@dataclass
class CutOptions:
    """What the fold needs beyond the proposal and the window."""

    speed: float = 1.0
    retakes: list[dict] | None = None
    #: Silence measured in the source audio; pause cuts are clamped to it.
    silence: list[tuple[float, float]] | None = None
    #: Word intervals from the transcript; a pause cut never crosses one, so the cut
    #: gate's mid-word rule holds even where a mis-timed word sits in measured silence.
    words: list[tuple[float, float]] | None = None


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
    for start, end in _drop_intervals(proposal, options.retakes, window, options):
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
                    options: CutOptions | None = None) -> list[tuple[float, float]]:
    """Merged, time-ordered source spans to DROP inside ``window`` — pause silence
    (gap past the kept breath) + whole retake cut spans, clamped to the window."""
    w0, w1 = window
    silence = options.silence if options else None
    words = options.words if options else None
    protected = _protected_spans(proposal)
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
        # a pause cut removes measured silence inside the approved gap, less the breath,
        # and never touches a protected beat
        for piece in _measured_drops((at_s, at_s + float(t["gap_s"])), residual, silence):
            for piece2 in _outside_words(piece, protected):
                for start, end in (_outside_words(piece2, words) if words else [piece2]):
                    start, end = max(start, w0), min(end, w1)
                    if end > start:
                        drops.append((start, end))
    for r in retakes or []:
        start = max(float(r["cutStartS"]), w0)
        end = min(float(r["cutEndS"]), w1)
        if end > start:
            drops.append((start, end))
    merged: list[tuple[float, float]] = []
    for start, end in sorted(d for d in drops if d[1] - d[0] >= MIN_DROP_S):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _outside_words(drop: tuple[float, float],
                   words: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The parts of a drop that none of ``words`` covers (also used for protected beats)."""
    pieces = [drop]
    for word_start, word_end in words:
        nxt: list[tuple[float, float]] = []
        for start, end in pieces:
            if word_end <= start or word_start >= end:
                nxt.append((start, end))
                continue
            if word_start > start:
                nxt.append((start, min(end, word_start)))
            if word_end < end:
                nxt.append((max(start, word_end), end))
        pieces = nxt
    return [(start, end) for start, end in pieces if end > start]


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
    ap.add_argument("--manifest", help="the asset manifest: --media must be the file it "
                    "records for --source, so cuts cannot be measured against another take")
    ap.add_argument("--transcript", help="the source transcript: a pause cut then never "
                    "crosses a word the transcript claims, wherever it thinks the word is")
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
    if a.media and a.manifest:
        _require_declared_media(a.media, a.manifest, a.source)
    silence = measured_silence(a.media) if a.media else None
    words = None
    if a.transcript:
        with open(a.transcript) as f:
            payload = json.load(f)
        claimed = [(float(w["start"]), float(w["end"]))
                   for u in payload.get("transcript", []) for w in u.get("words", [])]
        # Only words the audio does NOT clear as unspoken block a cut. That is the cut
        # gate's own rule (SourceEvidence.measured_silent), so a plan written here is not
        # refused there for cutting across a word whose claimed span is really silence.
        words = claimed if not a.media else [
            window for window in claimed
            if not _measurement(a.media).unspoken(*window, margin=0.0)]
    track = cut_track_from_pauses(proposal, a.source, window,
                                  CutOptions(a.speed, retakes, silence, words))
    out = {"cutTrack": track,
           "removedS": removed_seconds(track, window),
           "segments": len(track),
           "pauseCutsClampedToMeasuredSilence": silence is not None,
           "pauseCutsKeptOutOfClaimedWords": words is not None,
           "silenceSpansMeasured": len(silence) if silence is not None else None}
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "cutTrack"}))


if __name__ == "__main__":
    main()
