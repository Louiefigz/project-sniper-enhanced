#!/usr/bin/env python3
"""plan_lint_overlays — title-card + b-roll overlay-window lint checks.

Split from :mod:`plan_lint` (300-line logic ceiling): this module owns the
OVERLAY tracks' editorial checks — hook/title-card text + hold/overlap rules
and the b-roll insert identifier/window/purpose rules (including the
b-roll-under-a-title-card collision, which is why the two live together).
Called from ``plan_lint.lint``; verdict semantics are UNCHANGED by the split.
"""

from __future__ import annotations

from typing import Any

from edit_scope import lane_required, resolve_scope
from producer_config import HOOK_CARD, LINT


def _check_hook_card_text(text: str, tag: str, rep: Any) -> None:
    """Operator rule: ≤2 lines, ≤8 words, lines fit the safe box."""
    words = text.split()
    lines = text.split("\n")
    if len(words) > HOOK_CARD["max_words"]:
        rep.error(f"{tag}: {len(words)} words (max {HOOK_CARD['max_words']})")
    if len(lines) > HOOK_CARD["max_lines"]:
        rep.error(f"{tag}: {len(lines)} lines (max {HOOK_CARD['max_lines']})")
    for ln in lines:
        if len(ln) > HOOK_CARD["max_chars_per_line"]:
            rep.error(f"{tag}: line {ln!r} is {len(ln)} chars "
                      f"(max {HOOK_CARD['max_chars_per_line']})")


def _overlaps(span: tuple[float, float], spans: list[tuple[float, float]]) -> bool:
    """True when ``span`` intersects any already-collected title-card span."""
    s, e = span
    return any(s < pe and ps < e for ps, pe in spans)


def _short_hook_required(target: dict, rep: Any) -> bool:
    """Respect graphics ownership while preserving an explicit Restrained base kit."""
    if target.get("mode") != "short":
        return False
    owned = lane_required(target, "graphics")
    named_thesis = target.get("style") == "restrained"
    directive = (target.get("lanes") or {}).get("graphics")
    if named_thesis and (directive == "off" or resolve_scope(target) == "trim"):
        rep.error("target.style='restrained' requires a frame-one thesis hook, "
                  "but explicit graphics-off or trim scope forbids that request; "
                  "resolve the operator intent conflict")
        return False
    return owned or named_thesis


def check_title_cards(plan: dict, preset: dict, out_dur: float, rep: Any) -> None:
    """Hook-card presence (shorts), windows, hold times, overlap."""
    cards = plan.get("titleCards") or []
    if len(cards) > LINT["max_title_cards"]:
        rep.error(f"{len(cards)} titleCards (max {LINT['max_title_cards']})")
    hook_at_zero = False
    spans: list[tuple[float, float]] = []
    for i, c in enumerate(cards):
        tag = f"titleCards[{i}]"
        s, e = float(c.get("outStart", -1)), float(c.get("outEnd", -1))
        if not (0 <= s < e <= out_dur + 0.05):
            rep.error(f"{tag}: window [{s},{e}] outside output duration {out_dur:.1f}s")
        hold = e - s
        if hold < HOOK_CARD["hold_min_s"] or hold > HOOK_CARD["hold_max_s"]:
            rep.error(f"{tag}: hold {hold:.1f}s outside "
                      f"[{HOOK_CARD['hold_min_s']},{HOOK_CARD['hold_max_s']}]s")
        _check_hook_card_text(str(c.get("text", "")), tag, rep)
        if c.get("style") == "hook" and s <= 0.01:
            hook_at_zero = True
        if _overlaps((s, e), spans):
            rep.error(f"{tag}: overlaps another title card")
        spans.append((s, e))
    needs_hook = _short_hook_required(plan.get("target") or {}, rep)
    if needs_hook and HOOK_CARD["from_frame_one"] and not hook_at_zero:
        rep.error("short mode requires a style='hook' title card starting at 0.0 "
                  "(frame 1 doubles as cover + loop start)")


def check_broll(plan: dict, manifest: dict, preset: dict, rep: Any) -> None:
    """B-roll identifier / output-window / length / purpose rules.

    ``out_dur`` is recomputed from the (already-validated) cut track — it is a
    pure function of the plan — so this stays within the 4-argument ceiling.
    """
    from plan_lint import output_duration_s  # call-time: plan_lint imports us
    out_dur = output_duration_s(plan.get("cutTrack") or [])
    broll_ids = {b["id"] for b in manifest.get("broll", [])}
    cards = [(float(c["outStart"]), float(c["outEnd"]))
             for c in plan.get("titleCards") or [] if "outStart" in c]
    inserts = plan.get("brollTrack") or []
    if len(inserts) > LINT["max_broll_inserts"]:
        rep.error(f"{len(inserts)} b-roll inserts (max {LINT['max_broll_inserts']})")
    for i, b in enumerate(inserts):
        tag = f"brollTrack[{i}]"
        if b.get("assetId") not in broll_ids:
            rep.error(f"{tag}: assetId {b.get('assetId')!r} not in manifest")
        s, e = float(b.get("outStart", -1)), float(b.get("outEnd", -1))
        if not (0 <= s < e <= out_dur + 0.05):
            rep.error(f"{tag}: window [{s},{e}] outside output duration")
        if (e - s) > preset["broll_insert_max_s"]:
            rep.error(f"{tag}: insert {e - s:.1f}s exceeds max "
                      f"{preset['broll_insert_max_s']}s")
        if not b.get("reason"):
            rep.error(f"{tag}: missing reason — b-roll must be purposeful")
        if any(s < ce and cs < e for cs, ce in cards):
            rep.error(f"{tag}: b-roll under a title card window")
