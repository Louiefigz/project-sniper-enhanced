#!/usr/bin/env python3
"""Deterministic decisions for every produced-longform intro seam.

An empty transition list is not an editorial decision. Produced/full work may
keep a hook seam as a hard cut only when the plan records why that is cleaner
and binds evidence to that exact seam. Both the operator-intent gate and the
transcript-aware hook gate use this module so their coverage semantics cannot
drift. A checked/automatic transition lane still owes at least one real
transition; clean-hook receipts explain remaining seams, not replace it.
"""
from __future__ import annotations

from typing import Any

SEAM_TOLERANCE_S = 0.25
MIN_REASON_CHARS = 20
MIN_EVIDENCE_CHARS = 12


def intro_seams(cut_track: list[dict], hook_s: float) -> list[float]:
    """Internal output cut seams eligible for an intro transition decision."""
    times: list[float] = []
    running = 0.0
    for row in cut_track or []:
        speed = float(row.get("speed", 1.0)) or 1.0
        duration = max(0.0, float(row.get("end", 0.0))
                       - float(row.get("start", 0.0))) / speed
        running += duration
        times.append(running)
    return [time for time in times[:-1] if 0.0 < time < hook_s]


def _valid_rows(value: Any) -> list[dict]:
    """Time-bound seam evidence rows with meaningful written evidence."""
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)
            and isinstance(row.get("outTime"), (int, float))
            and not isinstance(row.get("outTime"), bool)
            and len(str(row.get("evidence") or "").strip())
            >= MIN_EVIDENCE_CHARS]


def _near(value: float, seam: float) -> bool:
    return abs(value - seam) <= SEAM_TOLERANCE_S


def authored_transition_seams(plan: dict, seams: list[float]) -> set[float]:
    """Eligible seams covered by an actual authored transition row."""
    rows = plan.get("transitions")
    if not isinstance(rows, list):
        return set()
    times = [float(row["outTime"]) for row in rows
             if isinstance(row, dict)
             and isinstance(row.get("outTime"), (int, float))
             and not isinstance(row.get("outTime"), bool)]
    return {seam for seam in seams if any(_near(time, seam) for time in times)}


def clean_hook_seams(plan: dict, seams: list[float]) -> set[float]:
    """Eligible seams covered by a meaningful hard-cut evidence row."""
    receipt = plan.get("transitionRationale")
    if not isinstance(receipt, dict) or receipt.get("decision") != "clean-hook":
        return set()
    if len(str(receipt.get("reason") or "").strip()) < MIN_REASON_CHARS:
        return set()
    rows = _valid_rows(receipt.get("seams"))
    return {seam for seam in seams
            if any(_near(float(row["outTime"]), seam) for row in rows)}


def unresolved_intro_seams(plan: dict, seams: list[float]) -> list[float]:
    """Seams with neither a transition nor clean-hook evidence."""
    resolved = authored_transition_seams(plan, seams) | clean_hook_seams(plan, seams)
    return [seam for seam in seams if seam not in resolved]


def valid_clean_hook_receipt(plan: dict, seams: list[float]) -> bool:
    """Whether a plan proves a clean hard-cut choice at every intro seam."""
    return bool(seams) and clean_hook_seams(plan, seams) == set(seams)
