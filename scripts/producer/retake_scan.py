#!/usr/bin/env python3
"""retake_scan — find retakes in ONE raw long-form take (no edited pair needed).

``study_edit_diff`` learned the editor's retake policy by diffing a raw take
against its *finished* edit — the surviving twin told it which take won. In
production the brain only has the RAW camera file. This module inverts the
study's insight: with no edit to compare against, a **near-duplicate utterance
that recurs a little later IS the retake signal** — the operator re-delivered the
line. It clusters those re-deliveries, scores each take for defects, and proposes
which take to KEEP (default: the LATER take, per the study's 3/3 finding) and
which spans to CUT.

Reuses ``study_edit_diff`` wholesale — the transcript loader, the fuzzy
near-duplicate ratio, the content-overlap test, the filler/hedge lexicon — so
this tool and the study agree on what "the same line, said twice" means. Pairs
with ``pause_scan`` (the other half of the doctrine: tighten silence before
cutting words); ``scan()`` returns both.

The winner is chosen DETERMINISTICALLY (later take). Take scoring never flips the
choice — it only raises ``needsOperator`` (verdict ``earlier-candidate``) when
the later take looks clearly worse than an earlier one, so a human eyeballs the
rare exception (study pair 2 / R21 produced the first earlier-wins event: flag,
never flip). Measures only; no edit_plan is authored.

Pair 2 also showed a re-delivered BLOCK ~65s downstream (a failed segment
re-taken wholesale after an interruption), beyond the utt-window. A second,
stricter LONG-RANGE pass searches ``retake_lookback_s`` seconds ahead: long
anchors only, higher fuzzy bar, and the candidate winner may be JOINED with its
successor (a block re-delivery re-splits utterances). Long-range finds are
always ``needsOperator`` — never auto-cut a minute of footage on fuzzy evidence.

CLI: retake_scan.py <raw.transcript.json> [--out proposal.json] [--pauses]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field

from rapidfuzz import fuzz

from edit import pause_scan
from producer_config import MODES
from edit.study_edit_diff import (FILLERS, RETAKE_RATIO, RETAKE_WINDOW, Utt,
                             _content_overlap, _is_filler, load)

_LF = MODES["longform"]
MIN_TWIN_CONTENT_WORDS = 3   # a take shorter than this can't anchor a retake match
CONTINUATION_GAP_S = 1.5     # an unterminated fragment this close to its next line
# Backward lead-in absorption: a failed take often opens with a short abandoned
# start ("So here's what I do." / "Oh,") before the matched line. Absorb such
# contiguous stumbles into the cut span so the whole failed take is removed.
LEADIN_MAX_GAP_S = 3.0       # only absorb across gaps this small (contiguous)
LEADIN_PARTIAL_RATIO = 75.0  # a lead-in partly re-delivered by the winner
FLAG_MARGIN = 0.75           # later take flagged only if this much worse than earlier
# A partial false start (an abandoned opening fragment) has far less content mass
# than the full take that replaced it. Its near-zero RAW defect count must not make
# the longer winner look "worse" and pull an operator in — the flag comparison is
# only fair between comparably-substantial rival deliveries.
PARTIAL_FALSESTART_WORDS = 4   # earlier take below this content mass = false start
PARTIAL_FALSESTART_FRAC = 0.5  # …or below this fraction of the winner's mass
# A restart re-opens with the anchor's FULL token sequence ("So to make this
# easy" -> "so to make this easy, I made..."): a retake even when consecutive.
# A continuation resumes mid-phrase ("then it's gonna be" -> "it's gonna be a
# total waste") and stays protected (pair-1 false-positive guard).
RESTART_PREFIX_RATIO = 90.0
# ABANDONED anchor (operator review 2026-07-10, FAILURE_LEDGER LL-010): an
# unterminated mid-sentence line ("...feed the same prompt,") whose content
# mostly re-appears in a later re-delivery IS a retake even when the restart
# rephrases the tail — the c0679 116.01s abandoned line scored 81.4 vs its
# 124.34s restart, 0.6 under RETAKE_RATIO, so the outtake gap survived into a
# slip-cover. Terminal punctuation is STRUCTURAL (the ASR's own sentence
# state), not regex semantics; the eased bar still requires the directional
# _content_overlap and both content-mass floors.
ABANDONED_RETAKE_RATIO = 78.0
# Long-range (beyond the utt window, within retake_lookback_s) is STRICTER —
# recaps/CTAs legitimately repeat a line minutes later; only a heavy verbatim
# block may match. Calibrated on both study pairs: pair 1 yields zero distant
# candidates even at ratio 80; pair 2's true block re-delivery scores 88/0.77.
DISTANT_MIN_CONTENT = 6      # anchor mass required to search far ahead
DISTANT_RATIO = 85.0         # fuzzy bar for distant matches (local: RETAKE_RATIO)
DISTANT_OVERLAP = 0.6        # anchor content mostly re-appears (as _content_overlap)
DISTANT_JOIN_UTTS = 2        # candidate winner may be joined with its successor(s)
# Defect weights (advisory only — never change the winner, just the flag).
_W_MARKER, _W_REPEAT, _W_HEDGE = 1.5, 1.0, 2.0


@dataclass
class RetakeProposal:
    """One re-delivered line: keep the later take, cut the earlier take(s)."""

    id: int
    line: str                    # the kept (winning) take's opening, quoted
    keepStartS: float
    keepText: str
    cutStartS: float
    cutEndS: float
    cutWordsRemoved: int
    cutSpanS: float
    removedText: str             # what the cut span deletes (evidence)
    loserDefect: float
    keepDefect: float
    needsOperator: bool
    note: str
    verdict: str = "later-wins"  # or "earlier-candidate" (flag, never flip)
    longRange: bool = False      # winner found beyond the utt window (seconds pass)
    loserIdxs: list[int] = field(default_factory=list)
    winnerIdxs: list[int] = field(default_factory=list)


def _content_words(u: Utt) -> int:
    """Count of non-filler content tokens (>2 chars) — the retake anchor mass."""
    return sum(1 for w in u.words if w.tok not in FILLERS and len(w.tok) > 2)


def _is_restart(u: Utt, v: Utt) -> bool:
    """``v`` re-opens with ``u``'s full token sequence — a verbatim restart."""
    ut = u.norm_text.split()
    head = " ".join(v.norm_text.split()[:len(ut)])
    return fuzz.ratio(" ".join(ut), head) >= RESTART_PREFIX_RATIO


def _is_twin(u: Utt, v: Utt) -> bool:
    """True if ``v`` (later) re-delivers the same line as ``u`` (earlier).

    The match is DIRECTIONAL — the earlier take's content must re-appear in the
    later one (``_content_overlap(u, v)``). This is the raw-only retake signal:
    a line got said again. The reverse direction is deliberately NOT accepted —
    a short later stumble whose few words happen to sit inside an earlier long
    sentence ("at the at the time") is a coincidence, not a re-delivery. The
    winner must carry the line's content mass too — a 2-content-word fragment
    ("we have the") can never be the take to keep.
    """
    if _content_words(u) < MIN_TWIN_CONTENT_WORDS \
            or _content_words(v) < MIN_TWIN_CONTENT_WORDS:
        return False
    abandoned = u.text.strip()[-1:] not in ".?!"
    if v.idx == u.idx + 1 and abandoned \
            and v.start - u.end < CONTINUATION_GAP_S and not _is_restart(u, v):
        return False   # unterminated fragment completed by its next line, not a retake
    # LL-010: an abandoned (unterminated) anchor gets the eased bar — its
    # restart legitimately rephrases the tail it never finished.
    bar = ABANDONED_RETAKE_RATIO if abandoned else RETAKE_RATIO
    if fuzz.token_set_ratio(u.norm_text, v.norm_text) < bar:
        return False
    return _content_overlap(u, v)


def _distant_twin(u: Utt, utts: list[Utt], j: int) -> bool:
    """Strict beyond-window twin test; ``utts[j]`` may join with successors.

    A block re-delivery re-splits utterances, so the anchor's line often spans
    the candidate winner AND its next utterance. Guards (long anchor, high
    ratio, directional overlap) keep recap/CTA repeats from matching. The BASE
    utterance must itself carry a real share of the anchor's content — a join
    is a superset, and token_set_ratio scores any superset 100, so without
    this floor an unrelated line just before the true twin would match.
    """
    ca = {w.tok for w in u.words if w.tok not in FILLERS and len(w.tok) > 2}
    if not ca:
        return False
    base = {w.tok for w in utts[j].words}
    if len(ca & base) / len(ca) < DISTANT_OVERLAP / 2:
        return False
    for k in range(1, DISTANT_JOIN_UTTS + 1):
        toks = [w.tok for v in utts[j:j + k] for w in v.words]
        if len(ca & set(toks)) / len(ca) < DISTANT_OVERLAP:
            continue
        if fuzz.token_set_ratio(u.norm_text, " ".join(toks)) >= DISTANT_RATIO:
            return True
    return False


def find_losers(utts: list[Utt], lookback: int,
                lookback_s: float | None = None) -> dict[int, list[Utt]]:
    """Map each utterance index that is re-delivered later to its later twin(s).

    Two passes: the local utt-window (``_is_twin``, unchanged pair-1 guards),
    then a stricter long-range pass over utterances starting within
    ``lookback_s`` seconds beyond that window (``_distant_twin``).
    """
    lookback_s = _LF["retake_lookback_s"] if lookback_s is None else lookback_s
    losers: dict[int, list[Utt]] = {}
    for i, u in enumerate(utts):
        twins = [v for v in utts[i + 1:i + 1 + lookback] if _is_twin(u, v)]
        if _content_words(u) >= DISTANT_MIN_CONTENT:
            j = i + 1 + lookback
            while j < len(utts) and utts[j].start - u.end <= lookback_s:
                if _distant_twin(u, utts, j):
                    twins.append(utts[j])
                j += 1
        if twins:
            losers[i] = twins
    return losers


def _repeats(u: Utt) -> int:
    """Consecutive duplicate tokens within one utterance (a "that that" stumble)."""
    toks = [w.tok for w in u.words]
    return sum(1 for a, b in zip(toks, toks[1:]) if a and a == b)


def _defect(take: list[Utt]) -> float:
    """Defect score of a take: markers + intra-utterance repeats + hedge density."""
    if not take:
        return 0.0
    toks = [w.tok for u in take for w in u.words]
    markers = sum(1 for u in take if _is_filler(u))
    repeats = sum(_repeats(u) for u in take)
    hedge = (sum(1 for t in toks if t in FILLERS) / len(toks)) if toks else 0.0
    return round(_W_MARKER * markers + _W_REPEAT * repeats + _W_HEDGE * hedge, 3)


def _is_partial_falsestart(removed: list["Utt"], winner: "Utt") -> bool:
    """The earlier take is an abandoned false start, not a rival delivery.

    A short abandoned fragment carries far less content mass than the take that
    replaced it, so its near-zero raw defect count is an artifact of length, not
    quality. When that holds, the later take is a CONFIDENT keep — never flagged
    as a possibly-better earlier rival. This is what makes a partial false-start
    opening (a re-taken line) auto-resolve instead of asking an operator.
    """
    loser_words = sum(_content_words(u) for u in removed)
    keep_words = _content_words(winner)
    return (loser_words < PARTIAL_FALSESTART_WORDS
            or loser_words < PARTIAL_FALSESTART_FRAC * keep_words)


def _cluster(loser_idxs: list[int]) -> list[list[int]]:
    """Group adjacent loser indices (gap ≤ RETAKE_WINDOW) into retake clusters."""
    clusters: list[list[int]] = []
    for idx in sorted(loser_idxs):
        if clusters and idx - clusters[-1][-1] <= RETAKE_WINDOW:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])
    return clusters


def _leadin_start(utts: list[Utt], first_idx: int, winner: Utt) -> int:
    """Extend backward over contiguous abandoned-start stumbles into the take.

    A failed take often opens with a short abandoned start or a false-start
    marker ("So here's what I do." / "Oh,") before the matched line. Absorb those
    contiguous utterances so the whole failed take is cut, not just its tail.
    """
    i = first_idx
    while i - 1 >= 0:
        p = utts[i - 1]
        if utts[i].start - p.end > LEADIN_MAX_GAP_S:
            break
        partial = (fuzz.token_set_ratio(p.norm_text, winner.norm_text)
                   >= LEADIN_PARTIAL_RATIO and _content_overlap(p, winner))
        marker = _is_filler(p) or (p.text.strip()[-1:] not in ".?!"
                                   and len(p.words) <= 4)
        if not (partial or marker):
            break
        i -= 1
    return i


def _pick_winner(utts: list[Utt], losers: dict[int, list[Utt]],
                 twins: dict[int, Utt]) -> Utt:
    """The EARLIEST re-delivery that is not itself re-taken again later.

    An intermediate failed take is a loser, never the winner — either it
    anchors its own twin (in ``losers``), or, when its own forward match was
    too weak to anchor, a LATER twin in the same cluster re-delivers it (the
    joined distant test catches the pair-2 block's middle take, 92/0.84).
    """
    def retaken_again(t: Utt) -> bool:
        return any(t2.start > t.end and _distant_twin(t, utts, t2.idx)
                   for t2 in twins.values())
    clean = [t for t in twins.values()
             if t.idx not in losers and not retaken_again(t)]
    return min(clean or twins.values(), key=lambda t: t.start)


def _winner_blockstart(utts: list[Utt], winner: Utt, removed: list[Utt]) -> Utt:
    """A distant winner may re-open a re-delivered BLOCK mid-way (the block
    re-splits utterances). Walk its start backward over predecessors that are
    time-contiguous with the winner and whose content the failed block already
    spoke — so the kept block's opening line is never cut. The reference
    excludes the contiguous tail itself (no self-matching)."""
    i = winner.idx
    while i - 1 >= 0 and utts[i].start - utts[i - 1].end <= LEADIN_MAX_GAP_S \
            and utts[i - 1].start > removed[0].start:
        i -= 1
    ref = {w.tok for u in removed if u.idx < i for w in u.words}
    start = winner
    for p in (utts[j] for j in range(winner.idx - 1, i - 1, -1)):
        c = {w.tok for w in p.words if w.tok not in FILLERS and len(w.tok) > 2}
        if len(c) < MIN_TWIN_CONTENT_WORDS or len(c & ref) / len(c) < DISTANT_OVERLAP:
            break
        start = p
    return start


def _note(winner: Utt, earlier: bool, long_range: bool) -> str:
    """Human-readable rationale for the proposal's verdict/flag."""
    if earlier:
        return "later take scored worse than an earlier one — verify"
    if long_range:
        return (f"long-range re-delivery (winner @{round(winner.start, 1)}s, "
                "beyond the utt window) — verify the whole span")
    return (f"keep the later take (@{round(winner.start, 1)}s); "
            "earlier take(s) are the defective delivery")


def _resolve_cluster(
        utts: list[Utt], losers: dict[int, list[Utt]], members: list[int],
) -> tuple[list[int], dict[int, Utt], Utt, list[int]]:
    """Pick the cluster's winner; split off members PAST it for re-queueing.

    Two independent retakes can sit within RETAKE_WINDOW of each other (pair 2:
    anchors 4 utts apart with separate winners). A member that starts after the
    winner cannot belong to this cut span — it is its own retake event.
    """
    twins = {t.idx: t for m in members for t in losers[m]}
    winner = _pick_winner(utts, losers, twins)
    post = [m for m in members if utts[m].start >= winner.start]
    if post and len(post) < len(members):
        members = [m for m in members if utts[m].start < winner.start]
        twins = {t.idx: t for m in members for t in losers[m]}
        winner = _pick_winner(utts, losers, twins)
        return members, twins, winner, post
    return members, twins, winner, []


def build_retakes(utts: list[Utt], losers: dict[int, list[Utt]],
                  lookback: int | None = None) -> list[RetakeProposal]:
    """Assemble one proposal per retake cluster: keep later, cut earlier."""
    lookback = _LF["retake_lookback_utts"] if lookback is None else lookback
    out: list[RetakeProposal] = []
    pending = _cluster(list(losers))
    while pending:
        members, twins, winner, requeue = _resolve_cluster(
            utts, losers, pending.pop(0))
        if requeue:
            pending.insert(0, requeue)
        cid = len(out)
        long_range = winner.idx - members[-1] > lookback
        loser_start = utts[_leadin_start(utts, members[0], winner)].start
        removed = [u for u in utts if loser_start <= u.start < winner.start]
        if long_range and removed:
            winner = _winner_blockstart(utts, winner, removed)
            removed = [u for u in removed if u.start < winner.start]
        winner_start = winner.start
        loser_defect, keep_defect = _defect(removed), _defect([winner])
        earlier = (keep_defect > loser_defect + FLAG_MARGIN
                   and not _is_partial_falsestart(removed, winner))
        out.append(RetakeProposal(
            id=cid, line=winner.text[:120], keepStartS=round(winner.start, 2),
            keepText=winner.text[:200], cutStartS=round(loser_start, 2),
            cutEndS=round(winner_start, 2),
            cutWordsRemoved=sum(len(u.words) for u in removed),
            cutSpanS=round(winner_start - loser_start, 2),
            removedText=" / ".join(u.text for u in removed)[:280],
            loserDefect=loser_defect, keepDefect=keep_defect,
            needsOperator=earlier or long_range,
            note=_note(winner, earlier, long_range),
            verdict="earlier-candidate" if earlier else "later-wins",
            longRange=long_range,
            loserIdxs=[u.idx for u in removed],
            winnerIdxs=sorted(twins)))
    return out


def analyze(raw_path: str, lookback: int | None = None,
            lookback_s: float | None = None) -> dict:
    """Detect retakes in a raw transcript; return the machine-readable proposal."""
    lookback = _LF["retake_lookback_utts"] if lookback is None else lookback
    lookback_s = _LF["retake_lookback_s"] if lookback_s is None else lookback_s
    utts = load(raw_path)
    losers = find_losers(utts, lookback, lookback_s)
    retakes = build_retakes(utts, losers, lookback)
    return {
        "retakeDefault": _LF["retake_default"],
        "lookbackUtts": lookback,
        "lookbackS": lookback_s,
        "retakeCount": len(retakes),
        "winnerLaterCount": len(retakes),   # the default verdict never flips
        "earlierCandidateCount":
            sum(r.verdict == "earlier-candidate" for r in retakes),
        "longRangeCount": sum(r.longRange for r in retakes),
        "needsOperatorCount": sum(r.needsOperator for r in retakes),
        "retakes": [asdict(r) for r in retakes],
    }


def scan(raw_path: str, lookback: int | None = None,
         lookback_s: float | None = None) -> dict:
    """Full raw-longform edit proposal: retakes + pause tightening in one blob."""
    report = analyze(raw_path, lookback, lookback_s)
    report["pauses"] = pause_scan.scan(raw_path)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Find retakes in a raw long-form take.")
    ap.add_argument("raw")
    ap.add_argument("--out", help="write full JSON proposal here")
    ap.add_argument("--pauses", action="store_true", help="also include pause scan")
    ap.add_argument("--lookback", type=int, help="override retake lookback (utts)")
    ap.add_argument("--lookback-s", type=float,
                    help="override long-range retake lookback (seconds)")
    args = ap.parse_args()
    fn = scan if args.pauses else analyze
    report = fn(args.raw, args.lookback, args.lookback_s)
    if args.out:
        json.dump(report, open(args.out, "w"), indent=2)
    summary = {
        "retakeCount": report["retakeCount"],
        "needsOperatorCount": report["needsOperatorCount"],
        "retakes": [
            {"id": r["id"], "keepStartS": r["keepStartS"],
             "cut": [r["cutStartS"], r["cutEndS"]], "words": r["cutWordsRemoved"],
             "verdict": r["verdict"], "longRange": r["longRange"],
             "needsOperator": r["needsOperator"], "line": r["line"]}
            for r in report["retakes"]],
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
