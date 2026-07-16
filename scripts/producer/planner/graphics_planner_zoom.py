#!/usr/bin/env python3
"""graphics_planner_zoom — MG-4 ZOOM proposer (MODE-KEYED, per R13).

The zoom half of the auto-graphics planner. The two formats INVERT the zoom's
role (REFERENCE_STYLE_STUDY.md R13), so the proposer branches on grammar:

LONG-FORM — SEMANTIC (zoom carries meaning, sparse):
* punch-IN on a thesis beat (study Rule 1: the stressed beat of a claim),
* pull-OUT reset on a topic boundary (Rule 2: a brief out-ramp to wide, since the
  engine floors at the wide baseline and can't pull below it),
* in→out BRACKET on the top-N thesis lines (Rule 3: the signature move, capped),
* slow RAMP under a long uncut, graphic-free stretch (Rule 4) — every move a
  departure from the preserved-wide baseline that resolves back (Rule 5).

SHORTS — RHYTHMIC (zoom IS the cut): a ~step_median punch alternated across the
cut segments so every cut is a reframe (odd shots punch tight, even shots hold the
wide base) — a balanced push-pull, not a lean-in; ramps/brackets are demoted to
manual texture, not auto-proposed (R13).

It never injects: the brain reviews the candidates, the operator vetoes, and only
accepted rows are merged. Brackets carry ``needsOperator``. Proposed entries are
``punchIns``-shaped (they drop straight into ``edit_plan.punchIns`` after review)
plus proposal-meta (kind/confidence/trigger/reason/evidence) the merge strips.

Split from ``graphics_planner`` to keep each file within the logic budget.
Doctrine + numbers: REFERENCE_STYLE_STUDY.md R13, LONGFORM_VISUAL_STUDY.md §2,
producer_config.MOTION["zoom"].
"""

from __future__ import annotations

from producer_config import MOTION
from planner import graphics_planner_rules as rules

_ZOOM = MOTION["zoom"]
_MAG = _ZOOM["magnitude"]
_PROP = _ZOOM["proposer"]


def build_zoom_proposal(triggers: list[dict], words: list[dict], mode: str,
                        out_dur: float, segments: list,
                        face_center: tuple[float, float] | None = None) -> dict:
    """Branch on the mode's grammar, then assemble the reviewable zoom proposal.

    ``face_center`` is the (cx, cy) of the plan's ``faceBBoxNorm`` (0..1). When
    given, every SEMANTIC candidate recomposes toward it and every ramp eases
    (MOTION_GRAMMAR_STUDY §1/§8: the pro's pushes ease + translate toward the face;
    a linear, fixed-center creep reads mechanical). The rhythmic (shorts) path is
    left byte-identical — its punches are cut-driven and snap by design (R13).
    """
    cfg = _ZOOM["by_mode"].get(mode) or _ZOOM["by_mode"]["longform"]
    if cfg["grammar"] == "rhythmic":
        accepted, rejected = _rhythmic_candidates(segments, cfg, out_dur), []
    else:
        thesis = [c for c in triggers if c["trigger"] == "thesis"]
        boundaries = [c for c in triggers if c["trigger"] == "topic-boundary"]
        cands = _thesis_candidates(thesis, words, out_dur, cfg["step_median"])
        cands += _boundary_candidates(boundaries, words, mode, out_dur)
        cands += _stretch_ramps(segments, cands, out_dur)
        cut_times = [round(seg.out_start, 3) for seg in segments]
        _apply_motion(cands, face_center, cut_times)
        accepted, rejected = _trim(cands)
    return {
        "punchIns": [_strip(c) for c in accepted],
        "rejected": rejected,
        "meta": {"grammar": cfg["grammar"], "candidateCount": len(accepted),
                 "brackets": sum(1 for c in accepted if c.get("bracket")),
                 "note": "PROPOSAL only — the brain reviews, the operator vetoes; "
                         "shorts=rhythmic (zoom is the cut), long-form=semantic."},
    }


# =========================================================================== #
# Rhythmic (shorts) — zoom IS the cut (R13).
# =========================================================================== #
def _rhythmic_candidates(segments: list, cfg: dict, out_dur: float) -> list[dict]:
    """Alternate a ~step_median punch across cut segments so every cut reframes.

    Odd segments punch tight; even segments hold the wide base — so adjacent shots
    always differ (a balanced push-pull, R13). Capped at the mode's cadence budget.
    """
    zoom = cfg["step_median"]
    out: list[dict] = []
    for i, seg in enumerate(segments):
        if i % 2 == 0:                       # even shots stay at the wide base
            continue
        s, e = round(seg.out_start, 3), round(min(out_dur, seg.out_end), 3)
        if e - s < 0.3:                      # too short to read as a reframe
            continue
        out.append({"outStart": s, "outEnd": e, "zoom": zoom, "kind": "punch-in",
                    "confidence": "high", "trigger": "cut-alternation",
                    "reason": "R13 shorts: zoom IS the cut — punch this shot tight; "
                              "the wide shots between it read as the alternating pull",
                    "evidence": f"cut segment {seg.index}"})
    allowed = max(1, round(cfg["cadence"]["per_min"] * out_dur / 60.0))
    if len(out) > allowed:                   # keep the proposal inside the budget
        keep = {int(k * len(out) / allowed) for k in range(allowed)}
        out = [c for j, c in enumerate(out) if j in keep]
    return out


# =========================================================================== #
# Semantic (long-form) candidate builders.
# =========================================================================== #
def _thesis_candidates(thesis: list[dict], words: list[dict], out_dur: float,
                       med: float) -> list[dict]:
    """Punch-ins on every thesis beat; the top-N HIGH lines become brackets."""
    ranked = sorted(thesis, key=lambda c: (-rules.conf_rank(c["confidence"]),
                                           -len(c["wordIndices"]), _beat(words, c)))
    high = [c for c in ranked if c["confidence"] == "high"]
    bracket_ids = {id(c) for c in high[:_ZOOM["bracket_max_per_video"]]}
    out: list[dict] = []
    for c in thesis:
        builder = _bracket_cand if id(c) in bracket_ids else _punch_cand
        out.append(builder(c, words, out_dur, med))
    return out


def _punch_cand(c: dict, words: list[dict], out_dur: float, zoom: float) -> dict:
    """An eased-attack push on the stressed beat, magnitude by IMPORTANCE.

    docs/studies/MEASURED_EDIT_GRAMMAR.md §1: the pro's pushes run +7-16% scaled by how
    much the word matters (the biggest, +14.5%, lands on the product name). We key
    magnitude on the beat's confidence as the importance proxy; ``_apply_motion``
    turns it into an eased ~0.9s attack. ``zoom`` (step_median) is the fallback.
    """
    s, e = _clamp(_beat(words, c), _PROP["punch_hold_s"], out_dur)
    mag = _PROP["push_zoom_by_conf"].get(c["confidence"], zoom)
    return {"outStart": s, "outEnd": e, "zoom": mag, "kind": "punch-in",
            "confidence": c["confidence"], "trigger": "thesis",
            "reason": "thesis — eased push on the stressed beat, magnitude by "
                      "importance (MEASURED_EDIT_GRAMMAR §1)",
            "evidence": c["text"]}


def _bracket_cand(c: dict, words: list[dict], out_dur: float, zoom: float) -> dict:
    """An in→out bracket: punch-in held, then release to wide (study Rule 3)."""
    s, e = _clamp(_beat(words, c),
                  _PROP["punch_hold_s"] + _PROP["bracket_release_s"], out_dur)
    hold = round(min(_PROP["punch_hold_s"], (e - s) * 0.66), 3)   # leave a tail
    return {"outStart": s, "outEnd": e, "zoom": zoom, "bracket": True,
            "holdS": hold, "kind": "bracket", "confidence": c["confidence"],
            "trigger": "thesis", "needsOperator": True,
            "reason": "thesis (top line) — punch-in then release to wide (study "
                      "Rule 3 bracket, the signature move)",
            "evidence": c["text"]}


def _boundary_candidates(boundaries: list[dict], words: list[dict], mode: str,
                         out_dur: float) -> list[dict]:
    """Topic boundaries → a brief pull-out reset to wide (study Rule 2)."""
    floor = MOTION["planner"]["topic_boundary_min_conf"][mode]
    rate = _MAG["ramp_rate_default"]
    out: list[dict] = []
    for c in boundaries:
        if rules.conf_rank(c["confidence"]) < rules.conf_rank(floor):
            continue
        s, e = _clamp(_beat(words, c), _PROP["punch_out_s"], out_dur)
        out.append({"outStart": s, "outEnd": e,
                    "ramp": {"direction": "out", "ratePctPerS": rate},
                    "kind": "punch-out", "confidence": c["confidence"],
                    "trigger": "topic-boundary",
                    "reason": "topic boundary — pull-out reset to wide (study Rule "
                              "2; the engine floors at the wide baseline)",
                    "evidence": c["text"]})
    return out


def _stretch_ramps(segments: list, existing: list[dict],
                   out_dur: float) -> list[dict]:
    """Carpet EVERY uncovered stretch in a segment with an eased ALIVENESS creep.

    The frame must never freeze (MOTION_GRAMMAR_STUDY G1/G2: never still >~20s).
    The carpet fills every gap the semantic zooms leave — the HEAD before the
    first zoom, each GAP between two zooms, AND the tail after the last — not just
    the post-last-zoom tail. (v2 filled only the tail: a segment with an early
    punch stayed frozen through its whole middle — measured on the C0679 intro
    e2e, seg0 was ~44s of 48s frozen despite two punches.) Tagged
    ``role:"aliveness"`` — a continuous background layer EXEMPT from the semantic
    zoom cadence budget (it is not an "event").
    """
    floor = _PROP["ramp_min_stretch_s"]
    rate = _MAG["ramp_rate_default"]
    out: list[dict] = []
    for seg in segments:
        seg_end = round(min(out_dur, seg.out_end), 3)
        # Covered windows (clamped to this segment), in output order.
        covered = sorted(
            (max(seg.out_start, c["outStart"]), min(seg_end, c["outEnd"]))
            for c in existing
            if c["outStart"] < seg_end and c["outEnd"] > seg.out_start)
        cursor = round(seg.out_start, 3)
        gaps: list[tuple[float, float]] = []
        for c_start, c_end in covered:
            if c_start - cursor > 0:
                gaps.append((cursor, round(c_start, 3)))
            cursor = max(cursor, round(c_end, 3))
        if seg_end - cursor > 0:
            gaps.append((cursor, seg_end))
        for g_start, g_end in gaps:
            if g_end - g_start <= floor:
                continue
            e = round(min(g_end, g_start + _ramp_len(g_end - g_start, rate)), 3)
            if _overlaps_any(g_start, e, existing) or _overlaps_any(g_start, e, out):
                continue
            out.append({"outStart": g_start, "outEnd": e,
                        "ramp": {"direction": "in", "ratePctPerS": rate},
                        "role": "aliveness",
                        "kind": "ramp", "confidence": "medium",
                        "trigger": "aliveness-creep",
                        "reason": f"{g_end - g_start:.0f}s uncovered stretch — an "
                                  "eased creep keeps the frame alive (G1/G2)",
                        "evidence": f"cut segment {seg.index}"})
    return out


# =========================================================================== #
# Motion quality — ease + face-recompose (MOTION_GRAMMAR_STUDY §1/§8).
# =========================================================================== #
def _apply_motion(cands: list[dict], face_center: tuple[float, float] | None,
                  cut_times: list[float]) -> None:
    """Give every semantic candidate the pro's motion quality, in place.

    * Every candidate recomposes toward the face (``centerX``/``centerY`` from
      ``face_center``) instead of scaling about the frame center — the pro's
      big pushes carry a ~287px translation toward the face (study §1, R16).
    * Every animated ramp eases (``ease:"smooth"`` smoothstep) instead of the
      linear creep ``punch_in.py`` defaults to.
    * A plain punch-in that lands MID-SHOT becomes an eased-attack push
      (``attackS``): it smoothly pushes in instead of snapping. A punch ON a cut
      stays a hard step — a step reads as intentional AT a cut (grammar G6, the
      pro snaps only on cuts). This is the dominant fix: the machine's punches
      were ~84% hard snaps in dead frames.

    Brackets keep their signature snap-in/hold/release. ``punch_in.parse_windows``
    reads centerX/centerY/attackS; with no ``face_center`` the crop stays centered.
    """
    eps = _PROP["punch_on_cut_eps_s"]
    attack = _PROP["push_attack_s"]
    for c in cands:
        if face_center is not None:
            c["centerX"] = round(min(1.0, max(0.0, face_center[0])), 4)
            c["centerY"] = round(min(1.0, max(0.0, face_center[1])), 4)
        if c.get("ramp") is not None:
            c["ease"] = "smooth"
        elif c.get("kind") == "punch-in" and not c.get("bracket"):
            on_cut = any(abs(c["outStart"] - ct) <= eps for ct in cut_times)
            if not on_cut:
                c["attackS"] = round(min(attack, (c["outEnd"] - c["outStart"]) * 0.5), 3)


# =========================================================================== #
# Trim + helpers.
# =========================================================================== #
def _trim(cands: list[dict]) -> tuple[list[dict], list[dict]]:
    """Greedy rank-first: strongest SEMANTIC zoom wins overlaps; enforce the
    bracket cap. Aliveness creeps are a continuous background layer built pop-safe
    (they butt against events, never overlap) — they bypass the semantic min-gap
    and never block an event."""
    gap = MOTION["planner"]["min_gap_s"]
    cap = _ZOOM["bracket_max_per_video"]
    ranked = sorted(cands, key=lambda c: (-rules.conf_rank(c["confidence"]),
                                          c["outStart"]))
    accepted: list[dict] = []
    rejected: list[dict] = []
    brackets = 0
    for c in ranked:
        if c.get("role") == "aliveness":
            accepted.append(c)
            continue
        clash = next((a["outStart"] for a in accepted
                      if a.get("role") != "aliveness"
                      and c["outStart"] < a["outEnd"] + gap
                      and a["outStart"] < c["outEnd"] + gap), None)
        if clash is not None:
            rejected.append(_reject(c, f"overlaps a stronger zoom at {clash:.1f}s "
                                    f"(min gap {gap}s)"))
            continue
        if c.get("bracket"):
            if brackets >= cap:
                rejected.append(_reject(c, f"bracket cap {cap} reached — the "
                                        "biggest lines only"))
                continue
            brackets += 1
        accepted.append(c)
    accepted.sort(key=lambda c: c["outStart"])
    return accepted, rejected


def _beat(words: list[dict], cand: dict) -> float:
    """Output-time of a candidate's first word — the stressed-beat anchor.

    A source-mapped topic boundary carries its resolved ``outSpan`` (its
    ``wordIndices`` index the SOURCE list, not ``words``), so read that first.
    """
    span = cand.get("outSpan")
    if span:
        return float(span[0])
    return float(words[cand["wordIndices"][0]]["start"])


def _clamp(start: float, hold: float, out_dur: float) -> tuple[float, float]:
    """Clamp a zoom window inside the output; always leaves start < end."""
    start = max(0.0, min(start, max(0.0, out_dur - 0.2)))
    return round(start, 3), round(min(out_dur, start + hold), 3)


def _ramp_len(dur: float, rate_pct: float) -> float:
    """Cap a ramp's length so its peak stays a comfortable ≤ +40% departure."""
    return min(dur, 0.40 / (rate_pct / 100.0))


def _overlaps_any(s: float, e: float, cands: list[dict]) -> bool:
    """True if [s,e] overlaps any candidate's window."""
    return any(s < c["outEnd"] and c["outStart"] < e for c in cands)


def _reject(cand: dict, why: str) -> dict:
    """A rejected-row for a zoom candidate dropped during the trim."""
    return {"trigger": cand["trigger"], "kind": cand["kind"],
            "outStart": cand["outStart"], "confidence": cand["confidence"],
            "evidence": cand.get("evidence", ""), "reason": why}


def _strip(cand: dict) -> dict:
    """Drop internal (underscore-prefixed) keys from a proposed entry."""
    return {k: v for k, v in cand.items() if not k.startswith("_")}


# =========================================================================== #
# CLI table (rendered by graphics_planner.format_table).
# =========================================================================== #
def _move(c: dict) -> str:
    """One-column description of a zoom candidate's move for the table."""
    if c.get("bracket"):
        return f"in {c['zoom']}→wide (hold {c['holdS']}s)"
    if c.get("ramp"):
        return f"ramp {c['ramp']['direction']} {c['ramp']['ratePctPerS']}%/s"
    return f"punch {c['zoom']}"


def zoom_table_lines(zoom: dict | None) -> list[str]:
    """The ZOOM proposal sub-table (accepted punchIns + reject count)."""
    if not zoom:
        return []
    meta = zoom["meta"]
    lines = ["", f"ZOOM PROPOSAL  [{meta.get('grammar', '?')}]  "
             f"({meta['candidateCount']} candidates, {meta['brackets']} brackets)", "",
             f"{'#':>2}  {'WINDOW':>13}  {'KIND':<10}  {'MOVE':<24}  "
             f"{'CONF':<6}  {'OP':<3}  EVIDENCE", "-" * 100]
    for i, c in enumerate(zoom["punchIns"], 1):
        op = "!" if c.get("needsOperator") else ""
        lines.append(f"{i:>2}  {c['outStart']:>6.2f}-{c['outEnd']:<6.2f}  "
                     f"{c['kind']:<10}  {_move(c):<24}  {c['confidence']:<6}  "
                     f"{op:<3}  {(c.get('evidence') or '')[:40]!r}")
    lines.append(f"    zoom-rejected: {len(zoom['rejected'])}")
    return lines
