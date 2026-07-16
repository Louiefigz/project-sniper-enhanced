#!/usr/bin/env python3
"""study_edit_diff — learn the editor's cut policy by diffing RAW vs EDITED.

The operator records a long-form take (one camera file, e.g. C0666) that
contains *retakes* — the same line delivered two or three times — plus false
starts, hedges and dead air. A human editor then trims it into the published
video. This module reconstructs, from two Deepgram word-level transcripts, what
the editor removed and (by reading the words) why, so PRODUCE LONGFORM can
imitate the policy.

Method (two complementary passes):

1. WORD-LEVEL alignment via ``difflib.SequenceMatcher(autojunk=False)`` over the
   normalised token streams. Because the editor preserves order, EDITED is
   largely an ordered subsequence of RAW: ``equal`` blocks are KEPT words,
   ``delete`` blocks (raw-only) are CUT words, ``insert`` blocks (edited-only)
   are content whose source is NOT in this camera file (b-roll VO / other
   cameras). This gives exact per-word KEPT/CUT flags and cut-point timestamps.

2. UTTERANCE-LEVEL fuzzy match via rapidfuzz ``token_set_ratio`` for the
   human-readable per-utterance verdict, plus adjacency clustering to find
   RETAKES (near-duplicate raw utterances) and decide which take the editor
   kept.

The script emits ONE machine-readable JSON blob (consumed by the write-up in
docs/studies/EDIT_DECISION_STUDY.md). It makes no aesthetic judgement — only measures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from rapidfuzz import fuzz

# --- tunables (calibrated on the C0666 pair, 2026-07-05) -------------------
KEPT_FRAC = 0.85          # >= this fraction of an utterance's words kept => KEPT
CUT_FRAC = 0.15           # <  this fraction kept => CUT; between => KEPT-TRIMMED
RETAKE_RATIO = 82.0       # token_set_ratio >= this => two raw utts are the same line
RETAKE_WINDOW = 4         # only cluster raw utts within this many neighbours
DEAD_AIR_GAP = 1.2        # inter-word silence (s) inside raw >= this => dead air
SHORT_UTT_WORDS = 5       # utterances this short are candidate stumbles/fillers

# Filler / hedge lexicon (data catalogue — exempt from the logic line limit).
FILLERS = {
    "um", "uh", "erm", "hmm", "mhm", "uhhuh", "like", "so", "okay", "ok",
    "right", "well", "yeah", "yep", "anyway", "basically", "actually",
    "literally", "honestly", "obviously", "essentially",
}
HEDGE_PHRASES = (
    "you know", "i mean", "kind of", "sort of", "i guess", "i think",
    "or whatever", "or something", "let me", "let's see", "hold on",
    "wait", "sorry", "scratch that", "start over", "one more time",
)
_TOKEN_RE = re.compile(r"[a-z0-9']+")


def norm(text: str) -> list[str]:
    """Lowercase word tokens with punctuation stripped."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Word:
    """One transcript word with its timing and normalised token."""

    text: str
    start: float
    end: float
    tok: str
    kept: bool = False          # set by the word-level alignment pass


@dataclass
class Utt:
    """One Deepgram utterance plus derived alignment/classification fields."""

    idx: int
    start: float
    end: float
    text: str
    words: list[Word]
    kept_frac: float = 0.0
    verdict: str = ""           # KEPT | KEPT-TRIMMED | CUT
    bucket: str = ""            # cut taxonomy bucket (CUT utterances only)
    retake_id: int = -1         # cluster id if part of a retake, else -1
    won: bool = False           # this take is the one the editor kept

    @property
    def dur(self) -> float:
        return round(self.end - self.start, 2)

    @property
    def norm_text(self) -> str:
        return " ".join(w.tok for w in self.words)


def load(path: str) -> list[Utt]:
    """Parse a transcribe.py transcript file into Utt objects."""
    obj = json.load(open(path))
    raw = obj["transcript"] if isinstance(obj, dict) else obj
    utts: list[Utt] = []
    for i, u in enumerate(raw):
        words = [
            Word(w.get("word", ""), float(w.get("start", 0)),
                 float(w.get("end", 0)), (norm(w.get("word", "")) or [""])[0])
            for w in (u.get("words") or [])
        ]
        utts.append(Utt(i, float(u["start"]), float(u["end"]),
                        u.get("text", "").strip(), words))
    return utts


def flat_words(utts: list[Utt]) -> list[Word]:
    """All Word objects across utterances, in time order."""
    return [w for u in utts for w in u.words]


# --- pass 1: word-level alignment ------------------------------------------

@dataclass
class AlignBlocks:
    """Raw-only (cut) and edited-only (inserted) word-index spans."""

    cut_spans: list[tuple[int, int]] = field(default_factory=list)
    insert_spans: list[tuple[int, int]] = field(default_factory=list)
    kept_words: int = 0


def align_words(raw_w: list[Word], ed_w: list[Word]) -> AlignBlocks:
    """Tag each raw word kept/cut and collect cut + edited-only spans."""
    sm = SequenceMatcher(None, [w.tok for w in raw_w],
                         [w.tok for w in ed_w], autojunk=False)
    blocks = AlignBlocks()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for w in raw_w[i1:i2]:
                w.kept = True
            blocks.kept_words += i2 - i1
        elif tag == "delete":
            blocks.cut_spans.append((i1, i2))
        elif tag == "insert":
            blocks.insert_spans.append((j1, j2))
        else:  # replace = raw cut + edited inserted at once
            blocks.cut_spans.append((i1, i2))
            blocks.insert_spans.append((j1, j2))
    return blocks


def score_utts(utts: list[Utt]) -> None:
    """Set kept_frac + verdict on each raw utterance from its words' flags."""
    for u in utts:
        if not u.words:
            u.verdict = "CUT"
            continue
        u.kept_frac = round(sum(w.kept for w in u.words) / len(u.words), 3)
        if u.kept_frac >= KEPT_FRAC:
            u.verdict = "KEPT"
        elif u.kept_frac < CUT_FRAC:
            u.verdict = "CUT"
        else:
            u.verdict = "KEPT-TRIMMED"


# --- pass 2: retake detection (kept/cut asymmetry anchored) -----------------

@dataclass
class RetakeEvent:
    """One re-delivered line: the cut take(s) and the surviving twin."""

    id: int
    loser_idxs: list[int]
    loser_start: float
    winner_start: float
    winner_later: bool          # the surviving take was recorded AFTER the cut
    loser_text: str
    winner_text: str


def _content_overlap(a: Utt, b: Utt) -> bool:
    """Do a's content words (non-filler, >2 chars) mostly appear in b?"""
    ca = {w.tok for w in a.words if w.tok not in FILLERS and len(w.tok) > 2}
    cb = {w.tok for w in b.words}
    if len(ca) < 2:
        return False
    return len(ca & cb) / len(ca) >= 0.6


def _nearest_twin(u: Utt, kept: list[Utt]) -> Utt | None:
    """Closest-in-time KEPT utterance that is a near-duplicate of u, else None.

    Nearest (not highest-scoring) so an immediate re-take beats a distant callback
    that legitimately re-uses the same phrase later in the video.
    """
    twins = [k for k in kept if k.idx != u.idx
             and fuzz.token_set_ratio(u.norm_text, k.norm_text) >= RETAKE_RATIO
             and _content_overlap(u, k)]
    return min(twins, key=lambda k: abs(k.idx - u.idx)) if twins else None


def detect_retakes(utts: list[Utt]) -> list[RetakeEvent]:
    """A CUT line whose twin survives elsewhere is a retake; group adjacent ones."""
    kept = [u for u in utts
            if u.verdict in ("KEPT", "KEPT-TRIMMED") and len(u.words) >= 3]
    losers: list[tuple[Utt, Utt]] = []
    for u in utts:
        if u.verdict != "CUT" or len(u.words) < 3:
            continue
        twin = _nearest_twin(u, kept)
        if twin is not None:
            losers.append((u, twin))
    events, cid = [], 0
    i = 0
    while i < len(losers):
        group = [losers[i]]
        while (i + 1 < len(losers)
               and losers[i + 1][0].idx - losers[i][0].idx <= RETAKE_WINDOW):
            i += 1
            group.append(losers[i])
        loser_utts = [g[0] for g in group]
        twin = group[0][1]
        for lu in loser_utts:
            lu.retake_id = cid
        twin.won = True
        events.append(RetakeEvent(
            cid, [lu.idx for lu in loser_utts],
            round(loser_utts[0].start, 1), round(twin.start, 1),
            twin.start > loser_utts[0].start,
            " / ".join(lu.text for lu in loser_utts)[:200], twin.text[:200]))
        cid += 1
        i += 1
    return events


def winner_positions(events: list[RetakeEvent]) -> dict[str, int]:
    """Tally whether the surviving take came later or earlier than the cut take."""
    return {
        "events": len(events),
        "winner_later": sum(e.winner_later for e in events),
        "winner_earlier": sum(not e.winner_later for e in events),
    }


# --- pass 3: cut taxonomy --------------------------------------------------

def _is_filler(u: Utt) -> bool:
    """Utterance is dominated by hedges/fillers or is a restart phrase."""
    toks = [w.tok for w in u.words]
    if not toks:
        return True
    if any(p in u.norm_text for p in HEDGE_PHRASES) and len(toks) <= 8:
        return True
    return sum(t in FILLERS for t in toks) / len(toks) >= 0.5


def _is_false_start(u: Utt, nxt: Utt | None) -> bool:
    """Short fragment that restarts into the following utterance's opening."""
    if len(u.words) > SHORT_UTT_WORDS:
        return False
    if u.text and u.text[-1] not in ".?!":
        if nxt and u.words and nxt.words:
            head = " ".join(w.tok for w in u.words[:3])
            nxt_head = " ".join(w.tok for w in nxt.words[:3])
            if head and fuzz.partial_ratio(head, nxt_head) >= 70:
                return True
        return True
    return False


def classify_cuts(utts: list[Utt]) -> None:
    """Assign a taxonomy bucket to every CUT / KEPT-TRIMMED utterance."""
    for i, u in enumerate(utts):
        if u.verdict == "KEPT":
            continue
        nxt = utts[i + 1] if i + 1 < len(utts) else None
        if u.retake_id != -1:
            u.bucket = "retake-loser"
        elif _is_filler(u):
            u.bucket = "filler-hedge"
        elif _is_false_start(u, nxt):
            u.bucket = "false-start"
        elif u.verdict == "KEPT-TRIMMED":
            u.bucket = "trim"
        else:
            u.bucket = "tangent-or-weak-alt"


# --- pass 4: dead air + stats ----------------------------------------------

def dead_air(utts: list[Utt]) -> tuple[float, int, list[dict]]:
    """Sum silence >= DEAD_AIR_GAP between consecutive raw words."""
    words = flat_words(utts)
    total, count, samples = 0.0, 0, []
    for a, b in zip(words, words[1:]):
        gap = b.start - a.end
        if gap >= DEAD_AIR_GAP:
            total += gap
            count += 1
            if len(samples) < 12:
                samples.append({"after": a.text, "before": b.text,
                                "at": round(a.end, 2), "gap": round(gap, 2)})
    return round(total, 1), count, samples


def kept_runs(raw_w: list[Word]) -> dict[str, float]:
    """Length stats (seconds) of maximal consecutive KEPT word runs."""
    runs, cur_start, cur_end = [], None, None
    for w in raw_w:
        if w.kept:
            cur_start = w.start if cur_start is None else cur_start
            cur_end = w.end
        elif cur_start is not None:
            runs.append(cur_end - cur_start)
            cur_start = None
    if cur_start is not None:
        runs.append(cur_end - cur_start)
    if not runs:
        return {"count": 0, "mean_s": 0.0, "max_s": 0.0}
    return {"count": len(runs), "mean_s": round(sum(runs) / len(runs), 1),
            "max_s": round(max(runs), 1)}


def cut_boundaries(raw_w: list[Word], cut_spans: list[tuple[int, int]]) -> dict:
    """Do cuts land on sentence boundaries? Inspect punctuation at span edges."""
    at_boundary, mid_sentence = 0, 0
    for i1, i2 in cut_spans:
        before = raw_w[i1 - 1].text if i1 > 0 else ""
        after_kept = raw_w[i2].text if i2 < len(raw_w) else ""
        starts_clean = (not before) or before[-1:] in ".?!,"
        ends_clean = (not after_kept) or after_kept[:1].isupper()
        if starts_clean and ends_clean:
            at_boundary += 1
        else:
            mid_sentence += 1
    return {"at_boundary": at_boundary, "mid_sentence": mid_sentence}


def _voiced(words: list[Word]) -> float:
    return round(sum(w.end - w.start for w in words), 1)


def build_report(raw: list[Utt], ed: list[Utt], blocks: AlignBlocks,
                 events: list[RetakeEvent]) -> dict:
    """Assemble the full machine-readable analysis blob."""
    raw_w, ed_w = flat_words(raw), flat_words(ed)
    da_s, da_n, da_samples = dead_air(raw)
    buckets: dict[str, dict] = {}
    for u in raw:
        if u.verdict == "KEPT":
            continue
        b = buckets.setdefault(u.bucket, {"count": 0, "seconds": 0.0})
        b["count"] += 1
        b["seconds"] = round(b["seconds"] + u.dur, 1)
    cut_words = sum(i2 - i1 for i1, i2 in blocks.cut_spans)
    ins_words = sum(j2 - j1 for j1, j2 in blocks.insert_spans)
    verdicts = {v: sum(u.verdict == v for u in raw)
                for v in ("KEPT", "KEPT-TRIMMED", "CUT")}
    return {
        "totals": {
            "raw_utts": len(raw), "edited_utts": len(ed),
            "raw_words": len(raw_w), "edited_words": len(ed_w),
            "raw_voiced_s": _voiced(raw_w), "edited_voiced_s": _voiced(ed_w),
            "raw_span_s": round(raw[-1].end - raw[0].start, 1),
            "edited_span_s": round(ed[-1].end - ed[0].start, 1),
            "kept_words": blocks.kept_words, "cut_words": cut_words,
            "edited_only_words": ins_words,
            "pct_raw_words_kept": round(100 * blocks.kept_words / len(raw_w), 1),
            "pct_edited_from_raw":
                round(100 * (len(ed_w) - ins_words) / len(ed_w), 1),
        },
        "verdicts": verdicts,
        "cut_buckets": buckets,
        "retakes": {"positions": winner_positions(events),
                    "events": [vars(e) for e in events]},
        "dead_air": {"total_s": da_s, "count": da_n, "samples": da_samples},
        "kept_runs": kept_runs(raw_w),
        "cut_boundaries": cut_boundaries(raw_w, blocks.cut_spans),
        "insert_spans": [
            {"words": " ".join(w.text for w in ed_w[j1:j2]),
             "at": round(ed_w[j1].start, 2)}
            for j1, j2 in blocks.insert_spans if j2 - j1 >= 4
        ],
    }


def analyze(raw_path: str, ed_path: str) -> tuple[dict, list[Utt], list[Utt]]:
    """Run all passes; return (report, raw_utts, edited_utts)."""
    raw, ed = load(raw_path), load(ed_path)
    blocks = align_words(flat_words(raw), flat_words(ed))
    score_utts(raw)
    events = detect_retakes(raw)
    classify_cuts(raw)
    return build_report(raw, ed, blocks, events), raw, ed


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff RAW vs EDITED long-form.")
    ap.add_argument("raw")
    ap.add_argument("edited")
    ap.add_argument("--out", help="write full JSON report here")
    ap.add_argument("--dump-utts", help="write per-utterance verdict TSV here")
    args = ap.parse_args()
    report, raw, _ = analyze(args.raw, args.edited)
    if args.out:
        json.dump(report, open(args.out, "w"), indent=2)
    if args.dump_utts:
        with open(args.dump_utts, "w") as fh:
            fh.write("idx\tstart\tend\tverdict\tbucket\tretake\twon\tkept_frac\ttext\n")
            for u in raw:
                fh.write(f"{u.idx}\t{u.start}\t{u.end}\t{u.verdict}\t{u.bucket}\t"
                         f"{u.retake_id}\t{int(u.won)}\t{u.kept_frac}\t{u.text}\n")
    json.dump(report["totals"], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
