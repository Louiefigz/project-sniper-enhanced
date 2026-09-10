#!/usr/bin/env python3
"""TEST ONLY: the authored TREATMENT copy for the ``longform-96`` program.

``_guided_longform_program`` owns the deterministic 96s cut and the eight
semantic beats it exposes; this module owns the other half a guided proposal
needs — the WORDS on the cards, the reason each card earns its beat, and the
per-seam receipts for the hard cuts. It is the Python stand-in for the brain's
step-4 output, written so the TypeScript guided fixture can compile it into a
v4 treatment proposal without inventing a single string.

It is SYNTHETIC OPERATOR TEST MATERIAL, not creative approval: every line of
copy is QUOTED (or lightly trimmed) from the kept words of the very utterance
that raised its beat, because ``claims_contract``'s LL-003 phrase grounding
and LL-009 coverage floor accept nothing else.

Two deliberate, gate-forced departures from the planner's
``recommendedAssignment`` / the naive "every card is a takeover" reading are
documented at :data:`KIND_OVERRIDES` and :data:`ANCHOR_BY_BEAT`; both are
proven by ``_guided_longform_treatment_check``, which runs the real CLIs.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile

from _guided_body_program import (BODY_PROGRAM, BODY_STYLE_RATIONALE,
                                  CONTRAST_BEAT, CONTRAST_CARD, body_kind)

from compile_timeline import compile_plan, remap_words
from graphics.comp_capabilities import capability_matrix
# The named source of truth for a template's visible-completion floor; reading
# it keeps the authored minimumHoldS from drifting off visual_entry_errors.
from graphics.template_visual_contract import visible_timing
from intro_transition_contract import intro_seams
from planner.motion_triggers import flatten_words
from producer_config import HOOK_CONTRACT_WINDOW_S, MOTION

SCHEMA_VERSION = 1
SCOPE = "TEST-ONLY-deterministic-treatment-copy-not-creative-approval"
GRAPHICS_STYLE = "cutaway-only"
GRAPHICS_STYLE_RATIONALE = (
    "This excerpt is one continuous talking head with no screen share and no "
    "b-roll pool, so the cards ARE the visual variety: every beat is carried "
    "by a full-canvas 16:9 cutaway rather than an overlay competing with the "
    "face, and every kind used is measured at 1920x1080 and holds to the cut. "
    "The three structurally largest beats ride own-screen takeovers — the "
    "longform retention budget allows exactly three at this length — and the "
    "remaining cards ride free-band so the same cutaway grammar covers all "
    "eight beats without inventing an overlay language the comps were never "
    "measured for.")
MAXIMUM_HOLD_S = float(MOTION["takeover_max_s"]["longform"])
SEAM_EVIDENCE_WORDS = 3         # kept words quoted either side of a seam

# chart-story REQUIRES numeric ``spec.data`` (graphics/template_catalog_contract
# ._chart_errors) and claims_contract owes every painted number to the spoken
# window; the closing contrast beat speaks no number, so the card would fail
# with "spec.data numeric copy '12,' is not spoken in the card's window".
# Since 2026-09-06 intro_semantic_contract drops SPOKEN_NUMBER_KINDS from such
# beats (run #4: template_usage had demanded chart-story as "globally feasible"),
# so the planner no longer recommends it here; this override remains the
# explicit compatible comparison form for that beat.
# The closing contrast beat is the body's only slot left for an eighth distinct
# kind (template_usage: 8 feasible for 8 windows once chart-story is excluded);
# nateherk-takeover is the compatible comparison form the scale beat cannot
# take (scoreboard is its only form). It sits at ~78 s, after the opening's
# ~62 s approval end, so the body compositor (pipHole) renders it, not the
# first opening profile, which refuses hole comps.
KIND_OVERRIDES = {("comparison", "contrast"): "nateherk-takeover"}

# plan_lint_motion caps own-screen takeovers at
# max(MOTION["takeover_max_count"]["longform"], own_screen_cap(out_dur)) = 3
# for a 95s output, and all eight beats owe a graphic, so five cards ride
# "free-band". nateherk-bullet-bars is pinned to own-screen because a
# free-band rail sits in motion.recompose's registered geometry and would owe
# a synced measured transform the motion lane (off here) cannot author.
ANCHOR_BY_BEAT = {
    ("thesis", "promise"): "free-band",
    ("comparison", "limitation"): "own-screen",
    ("process", "maturity-stage"): "free-band",
    ("evidence", "building-proof"): "own-screen",
    ("scale", "number"): "free-band",
    ("chapter", "topic-boundary"): "own-screen",
    ("process", "sequence"): "free-band",
    ("comparison", "contrast"): "free-band",
}

# Data catalog (exempt from the line budget): one authored card per beat, keyed
# by the beat's (shape, trigger) — stable semantics, never the content-hashed
# beatId. ``values`` overrides the measured specDefaults; every other declared
# key rides its exact measured default. ``alternatives`` are other kinds from
# the beat's own compatibleKinds.
_CARDS: dict[tuple[str, str], dict] = {
    ("thesis", "promise"): {
        "kind": "statement-card",
        "values": {"variant": "classic",
                   "text": "Let me show you how this whole thing works"},
        "alternatives": ["fragment-payoff", "kinetic-quote-wide"],
        "reason": "The opening promise is the whole video's thesis, so the "
                  "hook opens on the sentence itself instead of a bare head.",
        "selection": "A one-line promise is a thesis beat with no list, no "
                     "number and no sequence, which is exactly the "
                     "statement-card's single-sentence chassis.",
    },
    ("comparison", "limitation"): {
        "kind": "nateherk-bullet-bars",
        "values": {"eyebrow": "Prompts only", "eyebrowAccent": "ink",
                   "headlineLines": "Most teams try to run this|using only "
                                    "prompts",
                   "explainer": "That gives you a draft and the draft stalls",
                   "verdict": "the draft stalls"},
        "alternatives": ["nateherk-scoreboard", "nateherk-takeover"],
        "reason": "The speaker names the ceiling of the prompt-only approach, "
                  "so the card has to show the limit rather than restate it.",
        "selection": "'using only prompts' sets a bounded approach against a "
                     "better one, and bullet-bars is the comparison form that "
                     "paints a ceiling instead of a total.",
    },
    ("process", "maturity-stage"): {
        "kind": "nateherk-pipeline",
        "values": {"eyebrow": "This stage", "eyebrowAccent": "result",
                   "headlineLines": "At this stage your content system|is a "
                                    "folder",
                   "explainer": "Ideas go in and nothing ever comes back",
                   # nateherk-pipeline nodes are `num~label` pairs; every token spoken.
                   "nodes": "Ideas~go in|nothing~ever|comes~back",
                   "footChip": "nothing comes back", "footAccent": "result"},
        "alternatives": ["nateherk-rail", "whiteboard-map"],
        "reason": "The stage description is a flow that dead-ends, so the "
                  "card draws the flow the speaker says never completes.",
        "selection": "'At this stage your content system' names a stage in a "
                     "pipeline, and the pipeline comp is the only compatible "
                     "form that shows ideas entering and nothing leaving.",
    },
    ("evidence", "building-proof"): {
        "kind": "nateherk-ledger-dark",
        "values": {"eyebrow": "The exact engine", "eyebrowAccent": "process",
                   "headlineLines": "We're building the exact engine|we use "
                                    "daily",
                   "explainer": "It reads the footage and writes the plan",
                   "barLabel": "the render runs",
                   # ledger rows are `key~value`, grid items `num~label`.
                   "rows": "reads~the footage|writes~the plan|render~runs",
                   "grid": "chips", "gridItems": "reads~footage|writes~plan|runs~render",
                   "footChip": "watches itself", "footAccent": "result"},
        "alternatives": ["whiteboard-connector"],
        "reason": "This is the proof beat: the speaker claims the engine is "
                  "already running daily, so the card itemises that receipt.",
        "selection": "'We're building the exact engine we use daily' is an "
                     "evidence claim, and the dark ledger is the receipt "
                     "chassis that lists what the engine actually does.",
    },
    ("scale", "number"): {
        "kind": "nateherk-scoreboard",
        "values": {"eyebrow": "Every hour", "eyebrowAccent": "process",
                   "contextChips": "footage|viewer|guardrails",
                   "heroValue": "1,000", "heroLabel": "hours of footage",
                   # scoreboard tiles are `value~label`; strip chips need a
                   # `label~state` grammar whose state word is unspoken, so none.
                   "tiles": "survive~the tricks|lose~a viewer|guardrails~matter",
                   "stripChips": "", "limitLabel": "LIMIT",
                   "limitText": "Every hour of that can lose a viewer"},
        "alternatives": [],
        "reason": "The only number in the excerpt lands here, so the card "
                  "makes the thousand hours the thing on screen.",
        "selection": "'a thousand hours of footage' is a scale beat, and the "
                     "scoreboard is the single compatible form that paints a "
                     "hero figure with its limit beside it.",
    },
    ("chapter", "topic-boundary"): {
        "kind": "section-takeover",
        "values": {"title": "The last thing", "sub": "you need is patience"},
        "alternatives": ["agenda-slide", "whiteboard-map"],
        "reason": "'Okay so the last thing' is an explicit chapter turn, and "
                  "the edit should mark the boundary rather than glide past.",
        "selection": "A topic boundary with no list behind it wants a hard "
                     "section marker, not an agenda; the takeover states the "
                     "new chapter and gets out of the way.",
    },
    ("process", "sequence"): {
        "kind": "agenda-slide",
        "values": {"eyebrow": "The plan", "title": "The whole loop",
                   "num1": "", "title1": "You are training it",
                   "sub1": "while it trains you",
                   "num2": "", "title2": "Finally the whole loop runs",
                   "sub2": "while you sleep",
                   "num3": "", "title3": "You review the output",
                   "sub3": "and ship what earns it",
                   "num4": "", "num5": ""},
        "alternatives": ["nateherk-pipeline", "whiteboard-map"],
        "reason": "'Finally' closes an ordered sequence, so the card lays the "
                  "three steps out in the order the speaker says them.",
        "selection": "The pipeline form is already spent on the earlier stage "
                     "beat, and an ordered three-step recap reads as an "
                     "agenda rather than a flow diagram.",
    },
    ("comparison", "contrast"): {
        "kind": "nateherk-takeover",
        "values": {"eyebrow": "The whole idea", "eyebrowAccent": "result",
                   "headlineLines": "The build is a system|instead of a scramble",
                   "heroValue": "a system",
                   "heroLabel": "instead of a scramble",
                   "chips": "system|scramble|machine",
                   "compareLabel": "behind the machine"},
        "alternatives": ["nateherk-scoreboard", "nateherk-bullet-bars"],
        "reason": "The closing line sets the built system against the "
                  "scramble it replaces, so the card holds both sides.",
        "selection": "'instead of a scramble' is a direct contrast, and with "
                     "no spoken number to chart the takeover is the "
                     "compatible comparison form that carries the payoff.",
    },
}


def _card(beat: dict, kind: str | None = None) -> dict:
    """The authored card for one beat, keyed by its semantic (shape, trigger)."""
    key = (str(beat["shape"]), str(beat["trigger"]))
    if key == CONTRAST_BEAT and kind == "chart-story":
        return CONTRAST_CARD
    card = _CARDS.get(key)
    if card is None:
        raise KeyError(f"no authored treatment copy for beat {key}")
    return card


def anchor_for(beat: dict, program: dict | None = None) -> str:
    """The plan anchor this beat's card rides.

    plan_lint caps own-screen takeovers at ``own_screen_cap(outputDuration)``
    (graphics_planner_longform, floored at 3).  When the program's budget holds
    every designed beat as a takeover, all cards stay own-screen — the only
    presentation the first opening profile has qualified.  Below that budget the
    curated :data:`ANCHOR_BY_BEAT` mix applies.
    """
    if program is not None:
        from planner.graphics_planner_longform import own_screen_cap
        if own_screen_cap(float(program["meta"]["outputDurationS"])) >= len(program["meta"]["beatSummary"]):
            return "own-screen"
    return ANCHOR_BY_BEAT[(str(beat["shape"]), str(beat["trigger"]))]


def minimum_hold_s(kind: str, beat: dict) -> float:
    """Longest of the beat floor, the template completion floor, and 1.5s."""
    timing = visible_timing(kind, _card(beat, kind)["values"])
    return max(float(beat.get("minimumGraphicHoldS") or 0.0),
               timing[0] if timing else 0.0,
               float(MOTION["hold_min_s"]["longform"]))


def variables_for(kind: str, values: dict) -> list[dict]:
    """Every measured default key for ``kind``, in catalog order, overridden."""
    row = capability_matrix().get(kind)
    if row is None:
        raise KeyError(f"{kind!r} has no release-ready comp_capabilities row")
    defaults = row["specDefaults"]
    unknown = sorted(set(values) - set(defaults))
    if unknown:
        raise KeyError(f"{kind!r} does not declare {unknown}")
    return [{"name": name, "value": values.get(name, defaults[name])}
            for name in row["specFields"] if name in defaults]


def kept_words(program: dict) -> list[dict]:
    """The program's KEPT words in OUTPUT time, through the real timeline map."""
    from _guided_longform_program import SOURCE_ID, program_plan
    tmap = compile_plan(program_plan(program))
    words = remap_words(flatten_words(program["transcript"]), SOURCE_ID, tmap)
    return sorted(words, key=lambda word: float(word["start"]))


def program_beats(program: dict) -> tuple[list[dict], dict]:
    """The program's semantic beats and form allocation, computed in-process.

    Mirrors ``_guided_longform_check.direct_beats`` without needing the
    manifest on disk, so the cut-preview fixture can author the treatment in
    the same pass that writes the transcript.
    """
    from _guided_longform_program import program_plan
    from graphics.form_allocation import build_form_allocation
    from graphics.intro_semantic_contract import semantic_beats
    out_dur = compile_plan(program_plan(program)).output_duration
    beats = semantic_beats(kept_words(program), out_dur, None)
    preferred = {beat["beatId"]: beat["preferredKind"] for beat in beats
                 if beat.get("preferredKind")}
    return beats, build_form_allocation(beats, preferred)


def _quote(words: list[dict], lo: int, hi: int) -> str:
    """The kept words in ``[lo, hi)`` joined exactly as they were spoken."""
    return " ".join(str(word.get("word") or "") for word in words[lo:hi]).strip()


def seam_rows(program: dict, words: list[dict]) -> list[dict]:
    """One clean-hook receipt row per internal intro seam, quoting the cut."""
    hook_s = float(HOOK_CONTRACT_WINDOW_S["longform"])
    rows = []
    for seam in intro_seams(program["cutTrack"], hook_s):
        after = next((i for i, w in enumerate(words)
                      if float(w["start"]) >= seam), len(words))
        evidence = _quote(words, max(0, after - SEAM_EVIDENCE_WORDS),
                          after + SEAM_EVIDENCE_WORDS)
        rows.append({
            "outTime": round(seam, 4), "evidence": evidence,
            "reason": f"The cut at {seam:.2f}s falls between two complete "
                      f"sentences ({evidence!r}), so the narration already "
                      "carries the join and a rendered transition would only "
                      "decorate a boundary the ear accepts as spoken."})
    return rows


def _alternatives(card: dict, beat: dict, kind: str) -> list[str]:
    """The card's preferred alternatives restricted to this beat's ACTUAL compatible
    kinds (the binding rejects any other), topped up to the two the gate expects."""
    compatible = [item for item in beat["compatibleKinds"] if item != kind]
    preferred = [item for item in card["alternatives"] if item in compatible]
    rest = [item for item in compatible if item not in preferred]
    return (preferred + rest)[:max(len(preferred), min(2, len(compatible)))]


def _beat_row(beat: dict, kind: str, program: dict | None = None) -> dict:
    """One treatment beat: the chosen kind, its full variable set, and why."""
    card = _card(beat, kind)
    return {"beatId": str(beat["beatId"]), "shape": str(beat["shape"]),
            "outStart": float(beat["outStart"]), "kind": kind, "anchor": anchor_for(beat, program),
            "variables": variables_for(kind, card["values"]),
            "reason": card["reason"], "selectionReason": card["selection"],
            "alternativesConsidered": _alternatives(card, beat, kind),
            "minimumHoldS": minimum_hold_s(kind, beat),
            "maximumHoldS": MAXIMUM_HOLD_S}


def _kind_for(beat: dict, allocation: dict, program: dict | None = None) -> str:
    """The recommended kind, unless a gate forces a compatible alternative."""
    key = (str(beat["shape"]), str(beat["trigger"]))
    recommended = next((str(row["kind"]) for row
                        in allocation.get("recommendedAssignment") or []
                        if row.get("beatId") == beat["beatId"]), None)
    kind = body_kind(program, key) or KIND_OVERRIDES.get(key, recommended)
    if (program or {}).get("meta", {}).get("testProgramVariant") == BODY_PROGRAM:
        kind = body_kind(program, key) or _card(beat)["kind"]
    if kind is None:
        raise KeyError(f"beat {beat['beatId']} has no allocated kind")
    if kind not in beat["compatibleKinds"]:
        raise ValueError(f"{kind!r} is outside {beat['compatibleKinds']}")
    return kind


def build_treatment(program: dict, beats: list[dict],
                    allocation: dict) -> dict:
    """Return the authored, JSON-serializable treatment for this program.

    Args:
        program: ``_guided_longform_program.build_program()`` output.
        beats: ``graphics.intro_semantic_contract.semantic_beats`` rows for the
            program's OUTPUT-time kept words.
        allocation: ``graphics.form_allocation.build_form_allocation`` output.

    Returns:
        The closed treatment object written to ``source/test-treatment.json``.
    """
    return {
        "schemaVersion": SCHEMA_VERSION, "scope": SCOPE,
        "graphicsStyle": GRAPHICS_STYLE,
        "graphicsStyleRationale": (BODY_STYLE_RATIONALE
            if program["meta"].get("testProgramVariant") == BODY_PROGRAM else GRAPHICS_STYLE_RATIONALE),
        "beats": [_beat_row(beat, _kind_for(beat, allocation, program), program)
                  for beat in beats if beat.get("decisionRequired")],
        "seamEvidence": seam_rows(program, kept_words(program)),
    }


def main(argv: list[str] | None = None) -> int:
    """Build the treatment and prove it against the real gates and CLIs."""
    from _guided_longform_treatment_check import verify  # heavy planner imports
    parser = argparse.ArgumentParser(
        description="Build and empirically verify the TEST longform treatment")
    parser.add_argument("--out", help="directory to write the proof into")
    parser.add_argument("--duration", type=float, default=96.0,
                        help="OUTPUT duration budget in seconds")
    args = parser.parse_args(argv)
    root = args.out or tempfile.mkdtemp(prefix="guided-treatment-")
    os.makedirs(root, exist_ok=True)
    return verify(root, args.duration)


def write_treatment(path: str, treatment: dict) -> None:
    """Write the treatment JSON exactly as the fixture persists it."""
    with open(path, "w") as handle:
        json.dump(treatment, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
