#!/usr/bin/env python3
"""pause_scan — inter-sentence pause-tightening proposal for a RAW long-form take.

The edit-decision study (docs/studies/EDIT_DECISION_STUDY.md) found that **62% of the
reference video's length reduction was silence**, not words: an 18.6 s head
pre-roll plus 61.4 s of inter-sentence pause tightened out of an otherwise clean
take. So for PRODUCE LONGFORM, pause-tightening is the PRIMARY length lever — run
it BEFORE cutting any content.

This module walks one raw transcript's word timings, finds every gap ≥ the
configured threshold, and proposes trimming each down to a kept "breath"
(``pause_keep_residual_s``). It respects the *protected pause* doctrine: an
emphasis pause after a question (rhetorical "…?" → let it land) or a short thesis
line is flagged KEEP rather than trimmed, per the car3 protected-pause precedent.

It measures only — it authors no edit_plan. The brain reads the proposal, keeps
the protected beats, and folds the trims into the cut track. Reuses
``study_edit_diff`` for transcript loading so the two tools parse identically.

CLI: pause_scan.py <raw.transcript.json> [--out proposal.json] [--top N]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from producer_config import MODES
from edit.study_edit_diff import FILLERS, Utt, Word, _is_filler, flat_words, load

_LF = MODES["longform"]
# Emphasis-pause protection (doctrine, not tuned per-video): a pause right after
# a question always breathes; a pause after a SHORT declarative thesis breathes
# only when it is clearly deliberate (≥ this multiple of the trim threshold) AND
# the line is real content — never a filler/hedge or a retake marker ("K.",
# "Let me try that again."), whose trailing pause is dead air to cut, not a beat.
THESIS_MAX_WORDS = 6
THESIS_MIN_CONTENT_WORDS = 2
THESIS_PROTECT_MULT = 1.4
_SENT_END = ".?!"
MIN_DIAGNOSTIC_PAIRS = 20
HIGH_TOUCHING_PAIR_FRACTION = 0.95


def _content_words(u: Utt) -> int:
    """Non-filler content tokens (>2 chars) — a thesis needs real substance."""
    return sum(1 for w in u.words if w.tok not in FILLERS and len(w.tok) > 2)


@dataclass
class PauseTrim:
    """One inter-word gap and what to do with it."""

    at_s: float                 # gap start = previous word's end
    gap_s: float
    trim_s: float               # proposed silence to remove (0 when protected)
    residual_s: float           # breath kept after tightening
    kind: str                   # sentence-boundary | mid-sentence
    protected: bool             # KEEP this beat (emphasis) — do not trim
    after: str                  # word before the gap (evidence)
    before: str                 # word after the gap (evidence)
    reason: str


def _iter_gaps(utts: list[Utt]):
    """Yield ``(prev_word, next_word, gap_s, prev_utt)`` in time order.

    Walks words across utterance boundaries so a gap knows the utterance the
    word before it closed — needed to tell a deliberate thesis beat from the
    dead air after a retake marker.
    """
    prev: tuple[Word, Utt] | None = None
    for u in utts:
        for w in u.words:
            if prev is not None:
                a, au = prev
                yield a, w, round(w.start - a.end, 3), au
            prev = (w, u)


def _classify(a: Word, gap: float, prev_utt: Utt,
              threshold: float) -> tuple[str, bool, str]:
    """Return ``(kind, protected, reason)`` for one over-threshold gap."""
    end_char = a.text.strip()[-1:]
    is_sentence = end_char in _SENT_END
    kind = "sentence-boundary" if is_sentence else "mid-sentence"
    if end_char == "?":
        return kind, True, "emphasis: pause after a question — let it land (KEEP)"
    a_last = prev_utt.words and a is prev_utt.words[-1]
    if a_last and is_sentence and not _is_filler(prev_utt) \
            and _content_words(prev_utt) >= THESIS_MIN_CONTENT_WORDS \
            and len(prev_utt.words) <= THESIS_MAX_WORDS \
            and gap >= threshold * THESIS_PROTECT_MULT:
        return kind, True, "emphasis: deliberate beat after a short thesis line (KEEP)"
    return kind, False, ("tighten inter-sentence dead air" if is_sentence
                         else "tighten mid-sentence stall")


def timing_diagnostics(utts: list[Utt]) -> dict:
    """Describe transcript gaps without claiming acoustic silence or accuracy.

    Dense touching timestamps can be legitimate rapid speech or row-wrapping
    artifacts. This informational warning is not a new cut gate, VAD result,
    inferred silence range, or permission to retime/remove a word.
    """
    words = flat_words(utts)
    if any(type(value) not in (int, float) or not math.isfinite(value)
           for word in words for value in (word.start, word.end)):
        raise ValueError("pause diagnostics require finite numeric word bounds")
    gaps = [b.start - a.end for a, b in zip(words, words[1:])]
    if any(not math.isfinite(gap) for gap in gaps):
        raise ValueError("pause diagnostics require finite derived word gaps")
    touching = sum(gap == 0 for gap in gaps)
    fraction = touching / len(gaps) if gaps else 0.0
    warnings: list[dict] = []
    if len(gaps) >= MIN_DIAGNOSTIC_PAIRS and fraction >= HIGH_TOUCHING_PAIR_FRACTION:
        warnings.append({
            "code": "high_touching_boundary_rate",
            "message": "Most word boundaries touch. Missing transcript gaps do not "
                       "establish absent acoustic pauses; review source timing before cutting.",
        })
    return {
        "schemaVersion": 1, "evidenceKind": "transcript-word-gaps-only",
        "acousticSilenceQualified": False,
        "wordCount": len(words), "adjacentPairCount": len(gaps),
        "touchingPairCount": touching, "touchingPairFraction": round(fraction, 6),
        "maxPositiveGapS": round(max([0.0, *gaps]), 3),
        "absenceOfPausesEstablished": False, "warnings": warnings,
    }


def propose(utts: list[Utt], threshold: float | None = None,
            residual: float | None = None,
            recover_floor: float | None = None) -> dict:
    """Build the pause-tightening proposal for a loaded raw transcript."""
    threshold = _LF["pause_gap_threshold_s"] if threshold is None else threshold
    residual = _LF["pause_keep_residual_s"] if residual is None else residual
    recover_floor = (_LF["pause_recover_floor_s"] if recover_floor is None
                     else recover_floor)
    trims: list[PauseTrim] = []
    total_recoverable = 0.0
    for a, b, gap, prev_utt in _iter_gaps(utts):
        if gap >= recover_floor and a.text.strip()[-1:] != "?":
            total_recoverable += max(0.0, gap - residual)
        if gap < threshold:
            continue
        kind, protected, reason = _classify(a, gap, prev_utt, threshold)
        trim = 0.0 if protected else round(max(0.0, gap - residual), 3)
        trims.append(PauseTrim(
            at_s=round(a.end, 3), gap_s=gap, trim_s=trim,
            residual_s=residual if not protected else gap,
            kind=kind, protected=protected,
            after=a.text, before=b.text, reason=reason))
    proposed = [t for t in trims if not t.protected]
    protected = [t for t in trims if t.protected]
    return {
        "timingDiagnostics": timing_diagnostics(utts),
        "thresholdS": threshold,
        "keepResidualS": residual,
        "gapsOverThreshold": len(trims),
        "proposedTrimCount": len(proposed),
        "proposedTrimTotalS": round(sum(t.trim_s for t in proposed), 1),
        "protectedCount": len(protected),
        "totalRecoverableS": round(total_recoverable, 1),
        "proposedTrims": [asdict(t) for t in sorted(
            proposed, key=lambda t: t.trim_s, reverse=True)],
        "protectedPauses": [asdict(t) for t in protected],
    }


def scan(raw_path: str) -> dict:
    """Load a raw transcript and return the pause-tightening proposal."""
    return propose(load(raw_path))


def main() -> int:
    ap = argparse.ArgumentParser(description="Propose pause tightening on a raw take.")
    ap.add_argument("raw")
    ap.add_argument("--out", help="write full JSON proposal here")
    ap.add_argument("--top", type=int, default=10, help="print this many biggest trims")
    ap.add_argument("--threshold", type=float, help="override gap threshold (s)")
    ap.add_argument("--residual", type=float, help="override kept breath (s)")
    args = ap.parse_args()
    report = propose(load(args.raw), args.threshold, args.residual)
    if args.out:
        json.dump(report, open(args.out, "w"), indent=2)
    summary = {k: report[k] for k in (
        "thresholdS", "gapsOverThreshold", "proposedTrimCount",
        "proposedTrimTotalS", "protectedCount", "totalRecoverableS", "timingDiagnostics")}
    summary["top"] = [
        {"at": t["at_s"], "gap": t["gap_s"], "trim": t["trim_s"],
         "kind": t["kind"], "after": t["after"], "before": t["before"]}
        for t in report["proposedTrims"][:args.top]]
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
