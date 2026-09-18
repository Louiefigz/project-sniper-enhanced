#!/usr/bin/env python3
"""TEST ONLY: a deterministic ~96s long-form PROGRAM for mechanics qualification.

The guided-opening worker reuses the ordinary full-base render, so the fixture
program it runs on has to be a legitimately lintable long-form edit, not a
three-second stub.  This module owns that program: a synthetic word-timed
transcript, the transcript-bound cut that tightens its inter-sentence pauses,
and the removal decisions that account for every removed span.

It is SYNTHETIC OPERATOR TEST MATERIAL, declared as an ``excerpt``: nobody said
these sentences and no ASR produced these timings.  The sentences are chosen so
the deterministic detectors (``planner.motion_triggers``,
``graphics.intro_semantic_cues``) expose eight strong, well-spaced semantic
beats whose compatible 16:9 forms are all own-screen hold-to-cut cards with
all-scalar specs — the shapes a mechanics run can actually dress.

``main()`` is the empirical proof: it writes the program to a temp directory,
compares the in-process beats/allocation against the ones ``graphics_planner``
emits as a subprocess, and requires ``transcript_cut_contract --previsual`` to
pass on the same files.
"""
from __future__ import annotations

import argparse
import os
import tempfile

from _guided_body_program import BODY_PROGRAM, body_script

SOURCE_ID = "raw-1"
LONGFORM_FLOOR_S = 300.0  # producer_config MODES["longform"]["duration_floor_s"]
LEAD_IN_S = 0.10          # silence before the first word
WORD_GAP_S = 0.05         # silence between words inside one sentence
KEEP_PAD_S = 0.15         # kept air on each side of a sentence (< MAX_SEAM_SILENCE_S)
TAIL_S = 0.20             # silence after the last word
MIN_PAUSE_S = 0.60        # shortest inter-sentence pause
PAUSE_STEP_S = 0.05
PAUSE_CYCLE = 7           # pauses walk 0.60 .. 0.90 deterministically
_BASE_WORD_S = 0.28
_PER_CHAR_S = 0.017
_MAX_CHARS = 10

# Own-screen 16:9 hold-to-cut kinds with all-scalar specs and no asset defaults.
OWN_SCREEN_KINDS = frozenset({
    "statement-card", "whiteboard-list", "module-pipeline",
    "module-scoreboard", "module-ledger-dark", "module-bullet-bars",
    "agenda-slide", "kinetic-quote-wide", "chart-story", "section-takeover",
    "whiteboard-map"})

# Data catalog: one spoken sentence per row, with the beat it is written to
# expose (``None`` = deliberately inert connective speech).  Every inert line is
# screened against the high-confidence detectors so the beat set stays exactly
# the eight designed ones.
_SCRIPT: tuple[tuple[str, tuple[str, str] | None], ...] = (
    ("Let me show you how this whole thing works.", ("promise", "thesis")),
    ("The build is small and the payoff comes early.", None),
    ("Every piece here earns its place on screen.", None),
    ("Most teams try to run this using only prompts.",
     ("limitation", "comparison")),
    ("That gives you a draft and the draft stalls.", None),
    ("You end up rewriting the same paragraph all day.", None),
    ("At this stage your content system is a folder.",
     ("maturity-stage", "process")),
    ("Ideas go in and nothing ever comes back out.", None),
    ("The gap is rarely the writing itself.", None),
    ("We're building the exact engine we use daily.",
     ("building-proof", "evidence")),
    ("It reads the footage and writes the plan.", None),
    ("The render runs while the machine watches itself.", None),
    ("It has to survive a thousand hours of footage.", ("number", "scale")),
    ("Every hour of that can lose a viewer.", None),
    ("So the guardrails matter more than the tricks.", None),
    ("Okay so the last thing you need is patience.",
     ("topic-boundary", "chapter")),
    ("The system gets better every week it runs.", None),
    ("You are training it while it trains you.", None),
    ("Finally the whole loop runs while you sleep.", ("sequence", "process")),
    ("You review the output and ship what earns it.", None),
    ("The rest goes back into the queue for later.", None),
    ("The build is a system instead of a scramble.", ("contrast", "comparison")),
    ("That is the whole idea behind the machine.", None),
    ("You keep the taste and lose the busywork.", None),
    ("The work that remains is the work worth doing.", None),
    ("Give it a week and the difference is obvious.", None),
    ("That is what the rest of this video covers.", None),
)

# Inert body filler for the genuine >=300s long-form class.  Every line is
# screened against the high-confidence detectors and the intro cue catalog:
# no digits or number words, no ordinals or sequence connectives, no proper
# nouns or tool names, no contrast/comparative markers, no chapter openers,
# and none of the promise/stage/limit/proof/credibility phrases.  The eight
# designed beats therefore stay the only decisionRequired beats.
_FILLER: tuple[str, ...] = (
    "The edit keeps the words you actually said.",
    "It removes the silence and leaves the breath.",
    "A clean take stays whole from start to end.",
    "The graphics land on the words they explain.",
    "Each card holds until the cut carries it away.",
    "The audio stays one continuous voice track.",
    "Nothing on screen competes with the speaker.",
    "The pacing settles once the opening is done.",
    "The body of the video can breathe a little.",
    "A card appears when the words earn a picture.",
    "The system checks every frame before delivery.",
    "It measures loudness and watches for glitches.",
    "The review happens before anyone sees the file.",
    "The plan is the boundary the render obeys.",
    "The same plan renders the same video every run.",
    "That repeatability is what makes fixes cheap.",
    "The transcript is the map the edit follows.",
    "Every kept word still lands on its own frame.",
    "The cut never splits a word down the middle.",
    "A pause survives when the point needs the air.",
    "The picture stays steady under the voice.",
    "Loud and quiet parts sit at the same level.",
    "The music stays off unless somebody asks for it.",
    "A card with nothing new never ships.",
    "The review reads frames like a viewer would.",
    "Spelling on screen matches the spoken words.",
    "The colors on a card never fight the footage.",
    "A cut lands where a sentence already ended.",
    "The queue holds ideas that did not fit.",
    "The last approved version is never thrown away.",
    "Every failed attempt stays on the record.",
    "The clock keeps running through every retry.",
)


_CYCLE_SUFFIX = ("", " Every time.", " As before.", " On purpose.", " By design.",
                 " Without fuss.", " In practice.", " Quietly.", " Reliably.")


def _script_rows(duration_s: float, variant: str | None = None) -> tuple:
    """The designed script, then cycled inert filler for longer budgets."""
    rows = list(body_script(_SCRIPT, variant))
    for suffix in _CYCLE_SUFFIX:
        if sum(len(text.split()) for text, _ in rows) * 0.45 >= duration_s * 1.2:
            break
        rows.extend((f"{text}{suffix}", None) for text in _FILLER)
    return tuple(rows)


def _word_duration(token: str) -> float:
    """Length-derived speech duration in the 0.28-0.45s band."""
    chars = min(len(token.strip(".,'")), _MAX_CHARS)
    return round(_BASE_WORD_S + _PER_CHAR_S * chars, 4)


def _pause_after(index: int) -> float:
    """Inter-sentence pause: 0.60-0.90s, cycling deterministically."""
    return round(MIN_PAUSE_S + PAUSE_STEP_S * (index % PAUSE_CYCLE), 4)


def _lay_out_words(text: str, clock: float) -> list[dict]:
    """Word rows for one sentence, separated by WORD_GAP_S of silence."""
    words = []
    for token in text.split():
        end = round(clock + _word_duration(token), 4)
        words.append({"word": token, "start": clock, "end": end})
        clock = round(end + WORD_GAP_S, 4)
    return words


def _utterance_rows(duration_s: float, variant: str | None = None) -> list[dict]:
    """Lay the script on the source clock until the OUTPUT budget is spent."""
    rows: list[dict] = []
    clock, spent = LEAD_IN_S, 0.0
    for index, (text, beat) in enumerate(_script_rows(duration_s, variant)):
        words = _lay_out_words(text, clock)
        start, last_end = words[0]["start"], words[-1]["end"]
        seg_start = 0.0 if index == 0 else round(start - KEEP_PAD_S, 4)
        length = round(last_end + KEEP_PAD_S - seg_start, 4)
        if spent + length > duration_s:
            break
        spent = round(spent + length, 4)
        rows.append({"start": start, "end": last_end, "text": text,
                     "words": words, "index": index, "beat": beat,
                     "segStart": seg_start})
        clock = round(last_end + _pause_after(index), 4)
    return rows


def _cut_track(rows: list[dict], source_duration: float) -> list[dict]:
    """One kept range per sentence; the last one runs to the source end."""
    track = [{"sourceId": SOURCE_ID, "start": row["segStart"],
              "end": round(row["end"] + KEEP_PAD_S, 4), "speed": 1,
              "rationale": "Keep the complete spoken sentence: " + row["text"]}
             for row in rows]
    track[-1]["end"] = source_duration
    return track


def _removal_rows(rows: list[dict], track: list[dict]) -> list[dict]:
    """A dead_air decision for every removed inter-sentence silence."""
    removals = []
    for index, (left, right) in enumerate(zip(track, track[1:])):
        removals.append({
            "sourceId": SOURCE_ID, "start": left["end"], "end": right["start"],
            "kind": "dead_air",
            "rationale": "Tighten the silence between two complete sentences.",
            "evidence": {"beforeWord": rows[index]["words"][-1]["word"],
                         "afterWord": rows[index + 1]["words"][0]["word"],
                         "removedText": ""}})
    return removals


def _seams(track: list[dict]) -> tuple[list[float], float]:
    """Output-time jump-cut instants plus the total output duration."""
    seams, run = [], 0.0
    for cut in track:
        run = round(run + cut["end"] - cut["start"], 4)
        seams.append(run)
    return seams[:-1], seams[-1]


def build_program(duration_s: float = 96.0, variant: str | None = None) -> dict:
    """Return the JSON-serializable synthetic long-form program.

    Args:
        duration_s: OUTPUT-duration budget; whole sentences are laid down while
            they still fit, so the real output lands just under this.

    Returns:
        ``{"transcript", "cutTrack", "cutDecisions", "meta"}`` where
        ``transcript`` is the exact object the guided cut fixture writes to
        ``source/raw.transcript.json``.
    """
    if variant == BODY_PROGRAM and duration_s < LONGFORM_FLOOR_S + 12:
        raise ValueError("TEST full-body variant requires its 312s program budget")
    rows = _utterance_rows(duration_s, variant)
    if not rows:
        raise ValueError(
            f"duration_s={duration_s} cannot hold even one scripted sentence")
    source_duration = round(rows[-1]["end"] + TAIL_S, 4)
    track = _cut_track(rows, source_duration)
    seams, output_duration = _seams(track)
    return {
        "transcript": {"transcript": [
            {key: row[key] for key in ("start", "end", "text", "words")}
            for row in rows]},
        "cutTrack": track,
        "cutDecisions": {"schemaVersion": 1,
                         "removals": _removal_rows(rows, track)},
        "meta": {**({"testProgramVariant": variant} if variant else {}),
                 "sourceDurationS": source_duration,
                 "outputDurationS": output_duration,
                 "outputBudgetS": float(duration_s),
                 # Below the 300s longform floor the program is an operator-declared
                 # excerpt; at or above it, it is the genuine long-form class.
                 "excerpt": output_duration < LONGFORM_FLOOR_S,
                 "seamsOutS": seams,
                 "beatSummary": [{"utterance": row["index"],
                                  "trigger": row["beat"][0],
                                  "shape": row["beat"][1],
                                  "sentence": row["text"]}
                                 for row in rows if row["beat"]]},
    }


# The stored operator intent waives every engagement lane except graphics. The
# accepted cut's target MUST carry the same directives: guided V4 inherits the
# accepted target into every compiled candidate, and operator_intent_contract
# resolves a lane-less "produced" target to auto → blocked (long-form run #3,
# 2026-09-06). The cut fixture's PROJECT_INTENT reuses this exact object.
INTENT_LANES = {"motion": "off", "transitions": "off", "captions": "off", "broll": "off"}


def program_plan(program: dict) -> dict:
    """The previsual cut plan for this program; lane directives mirror the stored intent."""
    return {"planVersion": 1,
            "target": {"mode": "longform", "scope": "produced", "width": 1920,
                       "height": 1080, "fps": 30, "lanes": dict(INTENT_LANES),
                       **({"excerpt": True} if program["meta"]["excerpt"] else {})},
            "cutTrack": program["cutTrack"],
            "cutDecisions": program["cutDecisions"]}


def program_manifest(program: dict) -> dict:
    """The minimal source manifest the transcript-bound gates need."""
    return {"sources": [{"id": SOURCE_ID,
                         "duration": program["meta"]["sourceDurationS"],
                         "transcriptPath": "raw.transcript.json"}]}


def main(argv: list[str] | None = None) -> int:
    """Build the program, write it out, and prove it against the real gates."""
    from _guided_longform_check import verify   # local: heavy planner imports
    parser = argparse.ArgumentParser(
        description="Build and empirically verify the TEST longform program")
    parser.add_argument("--out", help="directory to write the program into")
    parser.add_argument("--duration", type=float, default=96.0,
                        help="OUTPUT duration budget in seconds")
    args = parser.parse_args(argv)
    root = args.out or tempfile.mkdtemp(prefix="guided-longform-")
    os.makedirs(root, exist_ok=True)
    return verify(build_program(args.duration), root)


if __name__ == "__main__":
    raise SystemExit(main())
