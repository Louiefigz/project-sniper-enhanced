#!/usr/bin/env python3
"""hook_contract — the HARD, content-derived contract for the intro/hook.

Why this exists: the measured grammar (docs/studies/MEASURED_EDIT_GRAMMAR.md) lives in
docs and in the brain's judgment, and NOTHING forced a render to contain it — so
zooms, graphics, transitions, and the credibility move kept getting MISSED. This
gate removes the brain as the single point of failure: it reads the transcript,
derives what the hook OWES (a named tool → a graphic; a credibility claim → a
credibility move; a strong beat → an importance-push; enough cuts; captions), and
FAILS a plan that does not discharge every in-scope obligation — naming the exact
beat and what is owed.

MALLEABLE (edit_scope): an obligation is enforced ONLY when its lane is the
system's to fill (``lane_required`` == "auto"). "trim"/"light" scopes and any
operator directive ("no b-roll", "I'll supply the graphics") DISCHARGE the
obligation — the operator's choice always wins, so a "just cut the silences" job
never fails for missing chips.

Pure ``check_hook_contract(plan, words_out, target, rep)`` + a CLI that loads the
plan/transcript/manifest and exits 1 on any unmet obligation (run it in the skill
flow as a MANDATORY pre-present gate).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from producer_config import HOOK_CONTRACT_WINDOW_S, MODES  # noqa: E402
from edit_scope import lane_required, resolve_scope  # noqa: E402
from graphics.intro_semantic_contract import check_intro_graphics  # noqa: E402
from intro_transition_contract import intro_seams, unresolved_intro_seams  # noqa: E402
from planner import motion_triggers as mt  # noqa: E402
from planner.graphics_planner_rules import is_generic_entity  # noqa: E402

DEFAULT_HOOK_WINDOW_S = 60.0   # fallback for an unknown mode
COVER_NEAR_S = 3.0          # a graphic covers an entity beat within this of it
CRED_COVER_S = 6.0          # a credibility move may land within this of the beat

# STRONG first-person credential cues — unambiguous credibility (kept deliberately
# narrow so we hard-fail only when a real credibility beat is present; the brain
# still owns the weaker/contextual calls). Finds WHERE, not WHAT (no copy).
_CRED_CUES = ("decade", "years", "founder", "i built", "i've built", "i'm building",
              "i have built", "i started", "i've spent", "i have spent", "i run",
              "i've run", "ceo", "my own brand", "my own clients")


def _hook_window_s(target: dict) -> float:
    """The contract's hook window — the dedicated per-mode value, NOT the ambiguous
    MODES.hook_window_s (shorts 3s / longform 30s are too small; see config)."""
    return float(HOOK_CONTRACT_WINDOW_S.get(
        target.get("mode", "short"), DEFAULT_HOOK_WINDOW_S))


def _word_text(w: dict) -> str:
    return (w.get("punctuated_word") or w.get("word") or "").lower()


def _credibility_beats(words: list[dict]) -> list[float]:
    """Output-time starts of hook windows carrying a STRONG credibility cue."""
    joined = " ".join(_word_text(w) for w in words)
    if not any(cue in joined for cue in _CRED_CUES):
        return []
    # Anchor to the first cue word's time (single credibility move per hook).
    for i, w in enumerate(words):
        window = " ".join(_word_text(x) for x in words[max(0, i - 1):i + 3])
        if any(cue in window for cue in _CRED_CUES):
            return [float(w.get("start", 0.0))]
    return [float(words[0].get("start", 0.0))]


def _entity_beats(words: list[dict]) -> list[tuple[str, float]]:
    """(text, output-time) of each SPECIFIC named entity in the hook. Generic
    categories ("AI", "software") are dropped via the SAME R12 blocklist the
    graphics planner uses — they earn no graphic, so they owe none."""
    out = []
    for c in mt.detect_all(words):
        if c.get("trigger") != "entity":
            continue
        text = c.get("text", "").strip(" ,.")
        if is_generic_entity(text):
            continue
        idx = c.get("wordIndices") or []
        t = float(words[idx[0]].get("start", 0.0)) if idx else 0.0
        out.append((text, t))
    return out


def _top_beat(words: list[dict]) -> float | None:
    """The strongest beat in the hook (a HIGH-confidence thesis/entity) — where the
    importance-push is owed. None if the hook carries no strong beat."""
    best = None
    for c in mt.detect_all(words):
        if c.get("confidence") != "high" or c.get("trigger") not in ("thesis", "entity"):
            continue
        idx = c.get("wordIndices") or []
        t = float(words[idx[0]].get("start", 0.0)) if idx else 0.0
        best = t if best is None else best
    return best


def _covers(entries: list[dict], t: float, near: float, start_key="outStart",
            end_key="outEnd") -> bool:
    for e in entries:
        if start_key not in e:
            continue
        s = float(e[start_key]); en = float(e.get(end_key, s))
        if s - near <= t <= en + near:
            return True
    return False


def _output_duration(cut_track: list[dict]) -> float:
    """Output seconds through the cutTrack (end-start over speed, summed)."""
    total = 0.0
    for r in cut_track or []:
        speed = float(r.get("speed", 1.0)) or 1.0
        total += max(0.0, float(r.get("end", 0.0)) - float(r.get("start", 0.0))) / speed
    return total


def _check_hook_density(plan: dict, target: dict, rep: Any) -> None:
    """FAIL on any hook still-gap over the mode's hook ceiling — the front-load WALL.

    A sparse intro is the top retention killer, so front-load here is enforced,
    not merely warned (as ``plan_lint_motion.check_pacing`` does). The first
    ``hook_window_s`` must be the DENSEST region of the cut; every still-gap that
    exceeds the mode's ``hook_still_gap_s`` inside it fails the plan. The brain
    closes them with ``planner.pacing.suggest_fills`` (cut / punch / b-roll /
    graphic). See docs/studies/PRODUCTION_ENVELOPE_STUDY.md.
    """
    from planner.pacing import pacing_report  # local: pulls producer_config
    from producer_config import MODES  # noqa: E402
    mode = target.get("mode", "")
    out_dur = _output_duration(plan.get("cutTrack") or [])
    if out_dur <= 0:
        return
    report = pacing_report(plan, out_dur, mode)
    for s, e in [(s, e) for s, e in report["gaps"] if e <= report["hook_window"]]:
        rep.error(f"hook: {e - s:.0f}s with NO visual change [{s:.0f}-{e:.0f}s] — the "
                  f"intro must change at least every {report['hook_gap']:.0f}s "
                  "(front-load: cut / punch / b-roll / graphic). Run "
                  "planner.pacing.suggest_fills and place the fills.")
    # The hook should also be the DENSEST region (front-load ratio). That stays a
    # WARN, not a wall: forcing a hard ratio deadlocks against the zoom-cadence cap
    # (≤6 zooms/60s) and, for genuinely back-loaded content, would demand fabricated
    # cuts. check_pacing already warns on it; we surface it here at plan time so the
    # brain front-loads the engaging lanes as far as the content + cadence allow.
    want = float((MODES.get(mode, {}).get("pacing") or {}).get("hook_front_load", 1.5))
    ratio = report["hook_ratio"]
    if ratio != float("inf") and ratio < want:
        rep.warn(f"hook: front-load {ratio:.2f}x below {want}x — the body is cut as "
                 f"hard as the intro ({report['hook_rate']:.0f} vs "
                 f"{report['body_rate']:.0f} changes/min). Front-load more of the "
                 "engaging lanes (graphics / b-roll / punches) into the hook.")


def _check_hook_opens_dressed(plan: dict, target: dict, rep: Any) -> None:
    """FAIL a produced longform whose hook opens as a bare talking head.

    PRO_INTRO_ENVELOPE (measured 2026-07-10): the pro's first graphic — an
    on-head kinetic build — opens within ~1s; the hook is NEVER a bare head.
    Enforced as: some graphicsTrack entry must start by the mode's
    ``hook_overlay_by_s`` (longform pacing config, default 4s).
    """
    if target.get("mode") != "longform":
        return
    cfg = (MODES.get("longform", {}).get("pacing") or {})
    by_s = float(cfg.get("hook_overlay_by_s", 0.0))
    if by_s <= 0:
        return
    starts = [float(g.get("outStart", 1e9)) for g in plan.get("graphicsTrack") or []]
    if not starts or min(starts) > by_s:
        rep.error(f"hook: no graphic/overlay opens by {by_s:.0f}s — the pro hook "
                  "is never a bare head (open with an on-head kinetic build, "
                  "PRO_INTRO_ENVELOPE)")


def check_hook_contract(plan: dict, words_out: list[dict], target: dict,
                        rep) -> None:
    """Fail (``rep.error``) on every in-scope, non-waived hook obligation the plan
    does not discharge. Warnings for the softer ones (transitions)."""
    hook_s = _hook_window_s(target)
    hw = [w for w in words_out if float(w.get("start", 1e9)) < hook_s]
    if not hw:
        return
    gfx = plan.get("graphicsTrack") or []
    broll = plan.get("brollTrack") or []
    pushes = [p for p in plan.get("punchIns") or []
              if p.get("role") != "aliveness" and "outStart" in p
              and float(p["outStart"]) < hook_s]

    # 1. Named entity -> a graphic (chip/badge/card) or operator b-roll on its beat.
    if lane_required(target, "graphics"):
        for text, t in _entity_beats(hw):
            if not (_covers(gfx, t, COVER_NEAR_S) or _covers(broll, t, COVER_NEAR_S)):
                rep.error(f"hook: named entity {text!r} at {t:.1f}s has no graphic — "
                          "the hook MUST cover a named tool/product (chip/badge/card)")
        _check_hook_opens_dressed(plan, target, rep)
        if (target.get("mode") == "longform"
                and resolve_scope(target) in ("produced", "full")):
            check_intro_graphics(plan, words_out,
                                 _output_duration(plan.get("cutTrack") or []), rep)

    # 2. Credibility beat -> a full-frame credibility CARD near it. (Deliberately a
    #    card, not the "PIP" takeover: pip_takeover.py is not wired into render.py,
    #    so a speaker-inset PIP renders an empty face hole — a full-frame statement
    #    card is the renderable, pro-legal form.)
    if lane_required(target, "credibility"):
        for t in _credibility_beats(hw):
            if not _covers(gfx, t, CRED_COVER_S):
                rep.error(f"hook: credibility beat at {t:.1f}s has no credibility "
                          "move — a full-frame credibility CARD is owed on the "
                          "'I built / decade' claim")

    # 3. Strong beat -> at least one importance-push in the hook. Only a produced/
    #    full job carries discrete pushes; "light" motion is aliveness creep only.
    if resolve_scope(target) in ("produced", "full") and lane_required(target, "motion"):
        top = _top_beat(hw)
        if top is not None and not pushes:
            rep.error(f"hook: strong beat at {top:.1f}s but NO importance-push in the "
                      "hook — the payload noun must get a push (MEASURED_EDIT_GRAMMAR §1)")
        # 3b. HOOK DENSITY — the intro must be the DENSEST region (front-load WALL).
        _check_hook_density(plan, target, rep)

    # 4. On-screen captions are a SHORTS format element ONLY — long-form has NONE
    #    (verified against the pro edits: the talking head runs clean; the earlier
    #    "long-form captions" reading was a lower-third edge false-positive, and the
    #    on-screen TEXT on long-form is full-frame CARDS, not running captions).
    #    Shorts default to burn=True.
    if lane_required(target, "captions") and target.get("mode") == "short":
        caps = plan.get("captions") or {}
        burn_on = caps.get("burn", MODES.get("short", {}).get("captions_burn", True))
        if not (burn_on or plan.get("captionsTrack")):
            rep.error("hook: a short needs on-screen captions but none will render — "
                      "set captions.burn (words-on-screen is a shorts format element)")

    # 5. Every produced/full intro seam needs either an authored transition or
    #    an evidence-backed receipt proving why that exact hard cut is cleaner.
    if lane_required(target, "transitions"):
        seams = intro_seams(plan.get("cutTrack") or [], hook_s)
        unresolved = unresolved_intro_seams(plan, seams)
        if unresolved:
            labels = ", ".join(f"{time:.2f}s" for time in unresolved)
            rep.error("hook: eligible intro seams have no transition and no "
                      f"evidence-backed clean-hook decision at {labels} — author "
                      "a transition there, or add transitionRationale "
                      "{decision:'clean-hook', reason, seams:[{outTime,evidence}]} "
                      "for each intentional hard cut (±0.25s)")


def _cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plan"); ap.add_argument("transcripts_dir"); ap.add_argument("manifest")
    a = ap.parse_args()
    from graphics_planner import output_words  # local: heavy import
    import plan_lint
    plan = json.load(open(a.plan)); manifest = json.load(open(a.manifest))
    words = output_words(plan, a.transcripts_dir, manifest)
    rep = plan_lint.Report()
    target = plan.get("target") or {}
    check_hook_contract(plan, words, target, rep)
    verdict = {"scope": resolve_scope(target), "ok": not rep.errors,
               "errors": rep.errors, "warnings": rep.warnings}
    print(json.dumps(verdict, indent=2))
    return 0 if not rep.errors else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
