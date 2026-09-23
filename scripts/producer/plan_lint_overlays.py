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

from producer_config import LINT


def check_title_cards(plan: dict, preset: dict, out_dur: float, rep: Any) -> None:
    """Reject retired house cards; native catalog projects own hook design and review."""
    if plan.get("titleCards"):
        rep.error("Legacy titleCards are retired; author a HyperFrames catalog title in the native project.")


def check_broll(plan: dict, manifest: dict, preset: dict, rep: Any) -> None:
    """B-roll identifier / output-window / length / purpose rules.

    ``out_dur`` is recomputed from the (already-validated) cut track — it is a
    pure function of the plan — so this stays within the 4-argument ceiling.
    """
    from plan_lint import output_duration_s  # call-time: plan_lint imports us
    out_dur = output_duration_s(plan.get("cutTrack") or [])
    broll_ids = {b["id"] for b in manifest.get("broll", [])}
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
