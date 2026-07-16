#!/usr/bin/env python3
"""graphics_planner — MG-4 auto-graphics PROPOSER (triggers → ranked proposal).

Today every graphic is hand-authored into ``edit_plan.json``. This module makes
the machine PROPOSE: given a cut plan + the source transcripts, it remaps the
KEPT words into output time, runs the deterministic trigger detectors
(``motion_triggers``), maps each trigger to a doctrine-legal template, prunes for
R12 legality + density, and emits a RANKED, reviewable graphics proposal — plus a
suggested treatment map. It NEVER injects into a plan: the brain (skill) reviews
the candidates, the operator vetoes, and only ACCEPTED rows are merged.

The planner is deterministic CODE that surfaces options; judgment stays with the
brain. Placement is a RENDER-time decision (free_space/graphics_anchors) — the
planner only picks an anchor PREFERENCE from the zone's visual state.

Pipeline: kept words → compile_timeline.remap_words (OUTPUT time) → detect_all →
candidate assembly (graphics_planner_rules) → density/R12 trim → proposal.

Aspect + longform grammar: the render target's aspect (default = the mode's
natural aspect: shorts 9:16, longform 16:9) gates every kind through the
MG-4.3 canvas filter, and talking-head longform zones are retargeted per
R14/R17/R18 (whiteboard cutaways / kinetic burns / receipts b-roll) — see
graphics_planner_longform.

graphics_style axis (the R14 contradiction, pair-2 study): "cutaway-only",
"overlay-rich" (pair-2: fragment-payoff burns, headroom
icon stacks, section-takeover chapter cards, gate-legal long-list cutaways,
R24 concept stock), or "face-bridge" (two-chassis Nate editorial grammar) —
see graphics_planner_style and graphics_planner_face_bridge. Produced/full longform must
persist an explicit target.graphicsStyle plus rationale; lighter scopes retain
the legacy default. Longform only; the shorts path never branches on it.

CLI:
    graphics_planner.py <plan.json> <transcripts_dir> <manifest.json>
        [--visual-state states.json] [--gap SECONDS] [--aspect W:H]
        [--style cutaway-only|overlay-rich|face-bridge] [--out proposal.json] [--json]
Prints a human-readable candidate table (unless --json); writes the proposal JSON
to --out (or stdout with --json). See .claude/skills/producer/SKILL.md.
"""

from __future__ import annotations

import json
import os
import string
import sys

from compile_timeline import compile_plan, remap_words
from edit_scope import resolve_lanes, resolve_scope
from graphics.form_allocation import build_form_allocation
from graphics.intro_semantic_contract import semantic_beats
from graphics.style_profiles import profile_name
from planner.motion_triggers import detect_all, flatten_words, momentum_zones
from producer_config import MOTION
from planner import graphics_planner_boundaries as boundaries
from planner import graphics_planner_density as density
from planner import graphics_planner_gauge as gauge
from planner import graphics_planner_illustration as illustration
from planner import graphics_planner_longform as longform
from planner import graphics_planner_receipts as broll
from planner import graphics_reference as reference
from planner import graphics_planner_rules as rules
from planner import graphics_planner_style as overlay_rich
from planner import graphics_planner_face_bridge as face_bridge
from planner import graphics_planner_zoom as zoomp

_PLANNER = MOTION["planner"]
_FACE_ANCHORS = MOTION["face_anchors"]


# =========================================================================== #
# Words: kept material remapped into OUTPUT time (the space graphics live in).
# =========================================================================== #
def _source_index(manifest: dict) -> dict:
    """Map sourceId → manifest source entry."""
    return {str(s.get("id")): s for s in (manifest.get("sources") or [])}


def _load_words(source: dict, transcripts_dir: str) -> list[dict]:
    """Flattened word list for one manifest source (via its transcriptPath)."""
    path = source.get("transcriptPath")
    if not path:
        return []
    if not os.path.isabs(path):
        path = os.path.join(transcripts_dir, path)
    with open(path) as handle:
        return flatten_words(json.load(handle))


def output_words(plan: dict, transcripts_dir: str, manifest: dict) -> list[dict]:
    """All KEPT words remapped to output time, merged across sources, time-sorted.

    Each cut range's source words are remapped through the compiled timeline; a
    source's transcript is loaded once even if it appears in several ranges.
    """
    tmap = compile_plan(plan)
    sources = _source_index(manifest)
    cache: dict[str, list[dict]] = {}
    used = {str(r.get("sourceId")) for r in plan.get("cutTrack") or []}
    remapped: list[dict] = []
    for sid in used:
        src = sources.get(sid)
        if src is None:
            continue
        if sid not in cache:
            cache[sid] = _load_words(src, transcripts_dir)
        remapped.extend(remap_words(cache[sid], sid, tmap))
    remapped.sort(key=lambda w: float(w["start"]))
    return remapped


# Topic boundaries ride the inter-topic PAUSE, which the cut trims — so they're
# detected on SOURCE words and mapped forward (graphics_planner_boundaries), while
# every other trigger stays on output words. See _source_topic_boundaries below.


def _source_topic_boundaries(plan: dict, transcripts_dir: str, manifest: dict,
                             tmap, gap_s: float) -> list[dict]:
    """Every source's boundaries detected on source time + mapped to output."""
    used = {str(r.get("sourceId")) for r in plan.get("cutTrack") or []}
    return boundaries.collect(_source_index(manifest), used,
                              lambda src: _load_words(src, transcripts_dir),
                              tmap, gap_s)


# =========================================================================== #
# Visual-state lookup → anchor preference + faceBBoxNorm.
# =========================================================================== #
def make_state_fn(states: list[dict] | None, zones: list[dict] | None,
                  global_bbox: list | None):
    """Return ``t → (state, faceBBoxNorm)`` from visual-state json / plan zones.

    Priority: an explicit visual-state zone containing ``t`` → the plan's
    treatmentMap zone → the plan's global faceBBoxNorm. Unknown → (None, bbox).
    """
    def _in(z: dict, t: float) -> bool:
        return float(z.get("outStart", 0)) <= t < float(z.get("outEnd", 0))

    def state_at(t: float) -> tuple[str | None, list | None]:
        for z in states or []:
            if _in(z, t):
                return z.get("state"), z.get("faceBBoxNorm") or global_bbox
        for z in zones or []:
            if _in(z, t):
                return z.get("visualState"), z.get("faceBBoxNorm") or global_bbox
        return None, global_bbox

    return state_at


def _face_center(plan: dict) -> tuple[float, float] | None:
    """The (cx, cy) of the plan's global ``faceBBoxNorm`` ``[x, y, w, h]`` (0..1).

    The zoom proposer recomposes its pushes toward this point (study §1/R16). No
    valid 4-number bbox → None, and the render falls back to a centered crop.
    """
    bbox = plan.get("faceBBoxNorm")
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
        return None
    try:
        x, y, w, h = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    return (x + w / 2.0, y + h / 2.0)


def _clamp_window(start: float, hold: float, mode: str, out_dur: float) -> tuple:
    """Clamp a graphic window to the mode's hold bounds and the output length."""
    hold_min = MOTION["hold_min_s"].get(mode, 1.0)
    hold_max = MOTION["hold_max_s"].get(mode, MOTION["hold_max_s"]["short"])
    hold = max(hold_min, min(hold, hold_max))
    start = max(0.0, min(start, max(0.0, out_dur - hold_min)))
    end = min(out_dur, start + hold)
    return round(start, 3), round(end, 3)


# =========================================================================== #
# Candidate assembly.
# =========================================================================== #
def _span_times(words: list[dict], indices: list[int]) -> tuple[float, float]:
    """(start, end) output time of a candidate's word span."""
    return float(words[indices[0]]["start"]), float(words[indices[-1]]["end"])


def _entity_records(cands: list[dict], words: list[dict],
                    corrections: dict) -> tuple[list[dict], list[dict]]:
    """Classify entity candidates: keep specific ones, reject generic ones (R12)."""
    kept: list[dict] = []
    rejected: list[dict] = []
    for c in cands:
        if c["trigger"] != "entity":
            continue
        text = c["text"]
        kind, icon = rules.classify_entity(text)
        if kind == "reject":
            rejected.append(_reject("entity", c["confidence"], text,
                                    f"R12: {text!r} is a generic category, not a "
                                    "specific product — no entity graphic"))
            continue
        start, end = _span_times(words, c["wordIndices"])
        display = rules.apply_corrections(text.strip(string.punctuation + " "),
                                          corrections)
        kept.append({"start": start, "end": end, "conf": c["confidence"],
                     "text": display, "icon": icon})
    kept.sort(key=lambda r: r["start"])
    return kept, rejected


def _group_entities(records: list[dict], mode: str) -> list[list[dict]]:
    """Fold specific entities spoken close together into one badge/chip group."""
    window = _PLANNER["entity_group_window_s"]
    slots = _PLANNER["max_slots"]
    groups: list[list[dict]] = []
    for rec in records:
        if (groups and rec["start"] - groups[-1][0]["start"] <= window
                and len(groups[-1]) < slots
                and not any(g["icon"] and g["icon"] == rec["icon"]
                            for g in groups[-1])
                and not any(g["text"].lower() == rec["text"].lower()
                            for g in groups[-1])):
            groups[-1].append(rec)
        else:
            groups.append([rec])
    return groups


def _entity_candidate(group: list[dict], mode: str, out_dur: float,
                      state_fn) -> dict:
    """One icon-badge (all marks) or chip-row (any missing mark) from a group."""
    out_start = group[0]["start"]
    all_icons = all(g["icon"] for g in group)
    kind = "icon-badge" if all_icons else "chip-row"
    spec: dict = {}
    for i, g in enumerate(group, start=1):
        at = round(max(0.0, g["start"] - out_start), 2)
        if kind == "icon-badge":
            spec[f"icon{i}"], spec[f"at{i}"] = g["icon"], at
        else:
            spec[f"chip{i}"], spec[f"icon{i}"], spec[f"at{i}"] = \
                g["text"], (g["icon"] or ""), at
    last = group[-1]["start"] + _PLANNER["entity_hold_s"][mode]
    start, end = _clamp_window(out_start, last - out_start, mode, out_dur)
    names = ", ".join(g["text"] for g in group)
    why = ("bare recognizable marks (R12: icon beats chip)" if all_icons
           else "no known mark — chips carry the text (R12)")
    cand = _base_candidate(kind, start, end, spec, "entity",
                           _max_conf(g["conf"] for g in group),
                           f"specific entit{'y' if len(group) == 1 else 'ies'} "
                           f"[{names}] — {why}", names, state_fn, mode)
    cand["_marks"] = [g["icon"] or g["text"].lower() for g in group]
    return cand


def _beat_candidate(c: dict, words: list[dict], mode: str, out_dur: float,
                    state_fn) -> dict | None:
    """A non-entity trigger → a template candidate (or None if unmapped/gated)."""
    kind, note = rules.template_for(c["trigger"], c["text"], mode)
    if kind is None:
        return None
    if c["trigger"] == "topic-boundary":
        floor = _PLANNER["topic_boundary_min_conf"][mode]
        if rules.conf_rank(c["confidence"]) < rules.conf_rank(floor):
            return "gated"
    span = c.get("outSpan")            # source-mapped boundary carries its window
    w_start, w_end = span if span else _span_times(words, c["wordIndices"])
    hold = max(_PLANNER["default_hold_s"][mode], w_end - w_start)
    start, end = _clamp_window(w_start, hold, mode, out_dur)
    spec = rules.seed_spec(kind, c["text"], 0.0)
    reason = f"{c['trigger']} on “{c['text']}” → {kind}"
    if note:
        reason = f"{reason} ({note})"
    built = _base_candidate(kind, start, end, spec, c["trigger"],
                            c["confidence"], reason, c["text"], state_fn, mode)
    built["_wi"] = list(c["wordIndices"])   # planner-internal (stripped later)
    return built


def _base_candidate(kind: str, start: float, end: float, spec: dict, trigger: str,
                    conf: str, reason: str, evidence: str, state_fn,
                    mode: str) -> dict:
    """Assemble a candidate dict, resolving anchor + faceBBoxNorm from state."""
    state, bbox = state_fn(start)
    anchor, needs = rules.anchor_for(kind, state, mode)
    cand = {"outStart": start, "outEnd": end, "kind": kind, "spec": spec,
            "anchor": anchor, "confidence": conf, "trigger": trigger,
            "reason": reason, "evidence": evidence}
    if needs:
        cand["needsOperator"] = True
    if anchor in _FACE_ANCHORS and bbox:
        cand["faceBBoxNorm"] = bbox
    return cand


def assemble(words: list[dict], mode: str, out_dur: float, corrections: dict,
             state_fn, gap_s: float,
             source_boundaries: list[dict] | None = None
             ) -> tuple[list[dict], list[dict]]:
    """Detect triggers and build every candidate + the first rejection batch.

    When ``source_boundaries`` is given, the OUTPUT-time topic-boundary hits are
    discarded and replaced by these source-mapped ones — the boundary signal is a
    pause the cut trims, so it can only be trusted on source time (build_proposal
    supplies them). Every other trigger stays on the output words.
    """
    raw = detect_all(words, gap_s=gap_s)
    if source_boundaries is not None:
        raw = [c for c in raw if c["trigger"] != "topic-boundary"]
        raw = raw + list(source_boundaries)
    records, rejected = _entity_records(raw, words, corrections)
    candidates = [_entity_candidate(g, mode, out_dur, state_fn)
                  for g in _group_entities(records, mode)]
    for c in raw:
        if c["trigger"] == "entity":
            continue
        built = _beat_candidate(c, words, mode, out_dur, state_fn)
        if built == "gated":
            floor = _PLANNER["topic_boundary_min_conf"][mode]
            rejected.append(_reject(c["trigger"], c["confidence"], c["text"],
                                    f"topic-boundary confidence {c['confidence']!r} "
                                    f"below {floor!r} floor for {mode} — likely "
                                    "dead air, not a chapter"))
        elif built is None:
            rejected.append(_reject(c["trigger"], c["confidence"], c["text"],
                                    f"no template maps trigger {c['trigger']!r}"))
        else:
            candidates.append(built)
    return candidates, rejected


# =========================================================================== #
# Small builders + top-level.
# =========================================================================== #
def _reject(trigger: str, conf: str, evidence: str, why: str) -> dict:
    return {"trigger": trigger, "confidence": conf, "evidence": evidence,
            "reason": why}


def _max_conf(confs) -> str:
    return max(confs, key=rules.conf_rank)


def _strip_internal(cand: dict) -> dict:
    return {k: v for k, v in cand.items() if not k.startswith("_")}


def _apply_scope(proposal: dict, target: dict) -> dict:
    """Emit ONLY the lanes the operator's scope + directives activated (edit_scope).
    ``trim`` proposes nothing; ``light`` keeps the aliveness creep but no discrete
    pushes/graphics/b-roll; ``produced``/``full`` are unchanged. A per-lane
    directive ("graphics": "off"/"operator"/assets) drops that lane too, so the
    proposal never contains work the operator said they'd handle."""
    lanes = resolve_lanes(target)
    if lanes["graphics"] != "auto":
        proposal["candidates"] = []
        proposal["gaugeBeats"] = []
        proposal["references"] = []
        proposal["introSemanticBeats"] = []
        proposal["formAllocation"] = build_form_allocation([])
        proposal["treatmentMap"] = []
    if lanes["broll"] != "auto":
        proposal["brollReceipts"] = []
        proposal["brollIllustration"] = []
        proposal.pop("brollConcept", None)
    if lanes["graphics"] != "auto":
        proposal["momentumZones"] = []   # a graphic/cut pacing hint — moot off-lane
    zoom = proposal.get("zoom") or {"punchIns": []}
    if lanes["motion"] != "auto":
        proposal["zoom"] = {**zoom, "punchIns": []}
    elif resolve_scope(target) == "light":
        proposal["zoom"] = {**zoom, "punchIns": [p for p in zoom.get("punchIns", [])
                                                 if p.get("role") == "aliveness"]}
    # Meta counts were computed before gating — refresh them so a stripped lane
    # doesn't report a phantom "N candidates" over an empty table (format_table).
    meta = proposal.get("meta") or {}
    meta["candidateCount"] = len(proposal.get("candidates") or [])
    meta["receiptCount"] = len(proposal.get("brollReceipts") or [])
    meta["illustrationCount"] = len(proposal.get("brollIllustration") or [])
    meta["referenceCount"] = len(proposal.get("references") or [])
    meta["introSemanticBeatCount"] = len(
        proposal.get("introSemanticBeats") or [])
    allocation = proposal.get("formAllocation") or {}
    meta["maximumFeasibleDistinctKinds"] = allocation.get(
        "maximumFeasibleDistinctKinds", 0)
    proposal["meta"] = meta
    return proposal


def build_proposal(plan: dict, transcripts_dir: str, manifest: dict,
                   states: list[dict] | None = None, gap_s: float = 1.5,
                   aspect: str | None = None, style: str | None = None) -> dict:
    """Full proposal: candidates + receipts + rejected + treatmentMap + meta.

    ``aspect`` is the render target's aspect ("16:9"/"9:16"); default = the
    plan target's aspect, else the mode's natural aspect (shorts 9:16,
    longform 16:9). It gates the MG-4.3 canvas filter and the R14/R17
    talking-head longform retarget (graphics_planner_longform).

    ``style`` is the graphics_style axis
    ("cutaway-only"/"overlay-rich"/"face-bridge"),
    threaded like aspect (param > plan.target.graphicsStyle > cutaway-only).
    Overlay-rich swaps the LONGFORM retarget for the pair-2 grammar
    (graphics_planner_style) and adds the R24 concept-stock lane; the
    cutaway-only proposal stays byte-identical to the pre-axis planner (no
    meta.style / brollConcept keys), and shorts never branch on the axis.
    """
    mode = (plan.get("target") or {}).get("mode", "short")
    aspect = longform.resolve_aspect(aspect, plan, mode)
    style = longform.resolve_style(style, plan)
    rich = style == "overlay-rich" and mode == "longform"
    bridge = style == "face-bridge" and mode == "longform"
    selected_profile = profile_name({**(plan.get("target") or {}),
                                     "graphicsStyle": style})
    words = output_words(plan, transcripts_dir, manifest)
    tmap = compile_plan(plan)
    out_dur = tmap.output_duration
    intro_beats = semantic_beats(words, out_dur, selected_profile) \
        if mode == "longform" else []
    preferred_key = "preferredForm" if selected_profile else "preferredKind"
    preferred = {row["beatId"]: row[preferred_key] for row in intro_beats
                 if row.get(preferred_key)}
    form_allocation = build_form_allocation(
        intro_beats, preferred, selected_profile)
    corrections = rules.merged_corrections(
        (plan.get("captions") or {}).get("corrections"))
    state_fn = make_state_fn(states, plan.get("treatmentMap"),
                             plan.get("faceBBoxNorm"))
    src_boundaries = _source_topic_boundaries(plan, transcripts_dir, manifest,
                                              tmap, gap_s)
    candidates, rejected = assemble(words, mode, out_dur, corrections,
                                    state_fn, gap_s, src_boundaries)
    ctx = longform.Ctx(words, mode, aspect, state_fn, out_dur, style)
    retarget = face_bridge.retarget if bridge else (
        overlay_rich.retarget if rich else longform.retarget)
    candidates, lf_rejected = retarget(candidates, ctx)
    budget_zones = plan.get("treatmentMap") or density.suggest_treatment_map(
        mode, out_dur, state_fn)
    accepted, trimmed = density.trim(candidates, budget_zones)
    receipt_rows = broll.propose(ctx)
    accepted, beaten = broll.apply_precedence(accepted, receipt_rows)
    accepted, cut_trimmed = longform.trim_own_screen(accepted, mode, out_dur)
    receipt_rows, receipts_covered = broll.suppress_covered(
        receipt_rows, accepted)
    illus_beats, illus_covered = illustration.suppress_covered(
        illustration.illustration_beats(ctx), receipt_rows, accepted)
    gauge_beats = gauge.gauge_beats(ctx)
    ref_beats, ref_covered = reference.suppress_covered(
        reference.reference_beats(ctx),
        accepted + receipt_rows + illus_beats + gauge_beats)
    all_triggers = detect_all(words, gap_s=gap_s)
    zoom_triggers = [c for c in all_triggers
                     if c["trigger"] != "topic-boundary"] + src_boundaries
    zoom = zoomp.build_zoom_proposal(zoom_triggers, words, mode, out_dur,
                                     tmap.segments, _face_center(plan))
    proposal = {
        "meta": {"mode": mode, "aspect": aspect,
                 "outputDurationS": round(out_dur, 3),
                 "keptWords": len(words), "candidateCount": len(accepted),
                 "receiptCount": len(receipt_rows),
                 "illustrationCount": len(illus_beats),
                 "referenceCount": len(ref_beats),
                 "introSemanticBeatCount": len(intro_beats),
                 "maximumFeasibleDistinctKinds":
                     form_allocation["maximumFeasibleDistinctKinds"],
                 "note": "PROPOSAL only — the brain reviews, the operator vetoes; "
                         "face-relative anchors need a faceBBoxNorm at merge "
                         "(run visual_state.py or reuse the plan's)."},
        "candidates": [_strip_internal(c) for c in accepted],
        "brollReceipts": receipt_rows,
        "brollIllustration": illus_beats,
        "gaugeBeats": gauge_beats,
        "references": ref_beats,
        "introSemanticBeats": intro_beats,
        "formAllocation": form_allocation,
        "rejected": rejected + lf_rejected + trimmed + beaten + cut_trimmed
                    + receipts_covered + illus_covered + ref_covered,
        "treatmentMap": density.suggest_treatment_map(mode, out_dur, state_fn),
        "zoom": zoom,
        "momentumZones": momentum_zones(all_triggers, words),
    }
    if rich:
        _apply_overlay_rich(proposal, ctx, receipt_rows, accepted)
    elif bridge:
        proposal["meta"]["style"] = ctx.style
        proposal["meta"]["visualProfile"] = selected_profile
        proposal["meta"]["maximumFeasibleDistinctForms"] = \
            form_allocation.get("maximumFeasibleDistinctForms", 0)
    return _apply_scope(proposal, plan.get("target") or {})


def _apply_overlay_rich(proposal: dict, ctx, receipt_rows: list[dict],
                        accepted: list[dict]) -> None:
    """Overlay-rich extras: meta.style + the R24 concept-stock lane.

    Stamped ONLY for overlay-rich so the cutaway-only proposal stays
    byte-identical to the pre-axis planner (operator instruction 2026-07-06:
    the default doctrine's output is the regression baseline)."""
    concept_rows, concept_rejected = broll.concept_lane(ctx, receipt_rows,
                                                        accepted)
    proposal["meta"]["style"] = ctx.style
    proposal["meta"]["conceptCount"] = len(concept_rows)
    proposal["brollConcept"] = concept_rows
    proposal["rejected"] = proposal["rejected"] + concept_rejected


# =========================================================================== #
# CLI + human-readable table.
# =========================================================================== #
def format_table(proposal: dict) -> str:
    """A compact operator-facing table of accepted candidates + rejects."""
    meta = proposal["meta"]
    style = f", {meta['style']}" if "style" in meta else ""
    lines = ["", f"GRAPHICS PROPOSAL  ({meta['mode']}, "
             f"{meta.get('aspect', '?')}{style}, {meta['outputDurationS']}s, "
             f"{meta['candidateCount']} candidates)", ""]
    lines.append(f"{'#':>2}  {'WINDOW':>13}  {'KIND':<18}  {'ANCHOR':<11}  "
                 f"{'CONF':<6}  {'OP':<3}  REASON")
    lines.append("-" * 100)
    for i, c in enumerate(proposal["candidates"], 1):
        op = "!" if c.get("needsOperator") else ""
        lines.append(f"{i:>2}  {c['outStart']:>6.2f}-{c['outEnd']:<6.2f}  "
                     f"{c['kind']:<18}  {c['anchor']:<11}  {c['confidence']:<6}  "
                     f"{op:<3}  {c['reason']}")
    if meta["mode"] == "longform":
        lines.append("")
        lines.append(f"    [{longform.density_note()}]")
        lines.extend(broll.table_lines(proposal.get("brollReceipts") or []))
        lines.extend(illustration.table_lines(
            proposal.get("brollIllustration") or []))
        if "brollConcept" in proposal:          # overlay-rich only (R24)
            lines.extend(broll.concept_table_lines(proposal["brollConcept"]))
    if proposal.get("gaugeBeats"):              # shorts milestone gauges
        lines.extend(gauge.table_lines(proposal["gaugeBeats"]))
    lines.extend(reference.table_lines(         # cross-format (both modes)
        proposal.get("references") or []))
    lines.append("")
    lines.append(f"REJECTED ({len(proposal['rejected'])}):")
    for r in proposal["rejected"]:
        ev = (r.get("evidence") or "")[:32]
        lines.append(f"    [{r.get('confidence','?'):<6}] {r['trigger']:<15} "
                     f"{ev!r:<34} — {r['reason']}")
    lines.extend(zoomp.zoom_table_lines(proposal.get("zoom")))
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> dict:
    """Positionals + flags; minimal parser (stdlib-only, matches sibling CLIs)."""
    args = {"plan": None, "dir": None, "manifest": None, "states": None,
            "gap": 1.5, "aspect": None, "style": None, "out": None,
            "json": False}
    positional = ["plan", "dir", "manifest"]
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--visual-state":
            args["states"], i = argv[i + 1], i + 2
        elif tok == "--gap":
            args["gap"], i = float(argv[i + 1]), i + 2
        elif tok == "--aspect":
            args["aspect"], i = argv[i + 1], i + 2
        elif tok == "--style":
            args["style"], i = argv[i + 1], i + 2
        elif tok == "--out":
            args["out"], i = argv[i + 1], i + 2
        elif tok == "--json":
            args["json"], i = True, i + 1
        elif positional:
            args[positional.pop(0)], i = tok, i + 1
        else:
            raise ValueError(f"unexpected argument: {tok}")
    if positional:
        raise ValueError("usage: graphics_planner.py <plan.json> <transcripts_dir> "
                         "<manifest.json> [--visual-state s.json] [--gap S] "
                         "[--aspect W:H] "
                         "[--style cutaway-only|overlay-rich|face-bridge] "
                         "[--out p.json] [--json]")
    return args


def main() -> None:
    try:
        a = _parse_args(sys.argv[1:])
        with open(a["plan"]) as f:
            plan = json.load(f)
        with open(a["manifest"]) as f:
            manifest = json.load(f)
        states = None
        if a["states"]:
            with open(a["states"]) as f:
                states = json.load(f)
        proposal = build_proposal(plan, a["dir"], manifest, states, a["gap"],
                                  a["aspect"], a["style"])
        if a["out"]:
            with open(a["out"], "w") as f:
                json.dump(proposal, f, indent=2)
        if a["json"]:
            print(json.dumps(proposal, indent=2))
        else:
            print(format_table(proposal))
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
