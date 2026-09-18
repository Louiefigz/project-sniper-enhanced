#!/usr/bin/env python3
"""Fail-closed release contract for executable visual style profiles."""
from __future__ import annotations

import math
from typing import Any

from graphics.pip_hole import entry_has_hole, hole_rect
from graphics.form_allocation import build_form_allocation
from graphics.intro_semantic_contract import semantic_beats
from graphics.style_profiles import (form_contract, profile, profile_name,
                                     target_errors)


def _present(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value is not None


def _interval(row: dict) -> tuple[float, float]:
    return float(row.get("outStart", 0.0)), float(row.get("outEnd", 0.0))


def _coverage(rows: list[dict], start: float, end: float) -> float:
    spans = sorted((max(start, a), min(end, b)) for a, b in
                   (_interval(row) for row in rows) if b > start and a < end)
    merged: list[tuple[float, float]] = []
    for left, right in spans:
        if right <= left:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return sum(right - left for left, right in merged) / max(0.001, end - start)


def _decision_entries(plan: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    entries = {str(row.get("id")): row for row in plan.get("graphicsTrack") or []
               if isinstance(row, dict) and row.get("id")}
    decisions = {str(row.get("graphicId")): row
                 for row in plan.get("graphicsDecisions") or []
                 if isinstance(row, dict) and row.get("decision") == "graphic"
                 and row.get("graphicId")}
    return entries, decisions


def _entry_errors(index: int, entry: dict, decision: dict,
                  selected_profile: str) -> list[str]:
    tag = f"graphicsTrack[{index}]"
    information_form = str(entry.get("informationForm") or "")
    contract = form_contract(selected_profile, information_form)
    if contract is None:
        return [f"{tag}: unknown/missing informationForm {information_form!r} "
                f"for visual profile {selected_profile!r}"]
    errors = []
    expected_kind, chassis = contract["kind"], contract["chassis"]
    if entry.get("kind") != expected_kind:
        errors.append(f"{tag}: informationForm {information_form!r} requires "
                      f"kind {expected_kind!r}, not {entry.get('kind')!r}")
    if entry.get("chassis") != chassis or decision.get("chassis") != chassis:
        errors.append(f"{tag}: informationForm {information_form!r} requires "
                      f"chassis {chassis!r} on track and decision")
    if decision.get("informationForm") != information_form:
        errors.append(f"{tag}: decision/track informationForm mismatch")
    spec = entry.get("spec") or {}
    missing = [key for key in contract["required"] if not _present(spec.get(key))]
    if missing:
        errors.append(f"{tag}: {information_form!r} missing required payload "
                      f"fields {missing}")
    for key, value in contract.get("fixedSpec", {}).items():
        if spec.get(key) != value:
            errors.append(f"{tag}: {information_form!r} requires spec.{key}="
                          f"{value!r}, not {spec.get(key)!r}")
    expected_anchor = contract.get("anchor") or (
        "beside-face" if chassis == "cream" else "own-screen")
    if entry.get("anchor") != expected_anchor:
        errors.append(f"{tag}: {information_form!r} must use anchor "
                      f"{expected_anchor!r}")
    if chassis == "dark":
        if entry.get("anchor") != "own-screen":
            errors.append(f"{tag}: dark face-bridge form must be own-screen")
        if not entry_has_hole(entry):
            errors.append(f"{tag}: dark face-bridge form has no active presenter hole")
        cfg = profile(selected_profile) or {}
        expected_rect = tuple(cfg.get("darkPresenterRect") or ())
        if entry_has_hole(entry) and hole_rect(str(entry.get("kind"))) != expected_rect:
            errors.append(f"{tag}: dark presenter hole does not match profile rect "
                          f"{expected_rect}")
    return errors


def _sequence_errors(rows: list[dict], cfg: dict,
                     maximum_distinct: int | None = None) -> list[str]:
    errors = []
    forms = [str(row.get("informationForm") or "") for row in rows]
    for left, right in zip(forms, forms[1:]):
        if left and left == right:
            errors.append(f"face-bridge repeats informationForm {left!r} in "
                          "consecutive windows")
    if len(rows) >= 4:
        distinct = len(set(forms))
        floor = math.ceil(float(cfg["minimumDistinctFormRatio"]) * len(rows))
        if maximum_distinct is not None:
            floor = min(floor, maximum_distinct)
        if distinct < floor:
            errors.append(f"face-bridge uses {distinct} information forms across "
                          f"{len(rows)} dense windows; needs {floor}")
        chassis = [("cream" if str(row.get("chassis", "")).startswith("cream")
                    else "dark" if str(row.get("chassis", "")).startswith("dark")
                    else str(row.get("chassis") or "overlay")) for row in rows]
        flips = sum(left != right for left, right in zip(chassis, chassis[1:]))
        flip_floor = max(1, math.ceil((len(rows) - 1) * 0.25))
        if not {"cream", "dark"}.issubset(set(chassis)) or flips < flip_floor:
            errors.append(f"face-bridge macro rhythm has {flips} cream/dark "
                          f"flip(s); needs both chassis and at least {flip_floor}")
    return errors


def _renderer_errors(rows: list[dict], cfg: dict) -> list[str]:
    """Reject renderer monotony across the complete excerpt, not just dense beats."""
    errors = []
    kinds = [str(row.get("kind") or "") for row in rows]
    if cfg.get("forbidAdjacentRendererReuse"):
        for left, right in zip(kinds, kinds[1:]):
            if left and left == right:
                errors.append(f"face-bridge repeats renderer {left!r} in "
                              "consecutive windows")
    renderer_cap = int(cfg.get("maximumRendererUses") or 0)
    if renderer_cap:
        for kind in sorted(set(kinds)):
            count = kinds.count(kind)
            if kind and count > renderer_cap:
                errors.append(f"face-bridge uses renderer {kind!r} {count} "
                              f"times; maximum is {renderer_cap}")
    return errors


def _zoom_errors(plan: dict, cfg: dict, start: float, end: float) -> list[str]:
    limit = float(cfg["maximumZoom"])
    errors = []
    for index, row in enumerate(plan.get("punchIns") or []):
        if row.get("role") == "recompose":
            continue
        left, right = _interval(row)
        zoom = row.get("zoom")
        if right <= start or left >= end or not isinstance(zoom, (int, float)):
            continue
        if float(zoom) > limit:
            errors.append(f"punchIns[{index}] zoom {float(zoom):g} exceeds "
                          f"face-bridge maximum {limit:g}; spend motion on modules")
    return errors


def _maximum_dense_forms(words: list[dict] | None, out_dur: float,
                         selected_profile: str, start: float,
                         end: float) -> int | None:
    if words is None:
        return None
    beats = [row for row in semantic_beats(words, out_dur, selected_profile)
             if start <= float(row.get("outStart", 0.0)) < end]
    allocation = build_form_allocation(
        beats, selected_profile=selected_profile)
    return int(allocation.get("maximumFeasibleDistinctForms") or 0)


def check_style_profile(plan: dict, out_dur: float, rep: Any,
                        words: list[dict] | None = None) -> None:
    """Validate profile payload, two-chassis rhythm, density, and parity."""
    target = plan.get("target") or {}
    issues = target_errors(target)
    for issue in issues:
        rep.error(f"visual profile: {issue}")
    selected_profile = profile_name(target)
    cfg = profile(selected_profile)
    if cfg is None:
        return
    entries, decisions = _decision_entries(plan)
    rows = sorted(entries.values(), key=lambda row: _interval(row)[0])
    for index, entry in enumerate(rows):
        decision = decisions.get(str(entry.get("id")))
        if decision is None:
            rep.error(f"graphicsTrack[{index}]: face-bridge graphic is not bound "
                      "to a graphicsDecisions row")
            continue
        for issue in _entry_errors(index, entry, decision, selected_profile):
            rep.error(issue)
    for issue in _renderer_errors(rows, cfg):
        rep.error(issue)
    start = float(cfg["denseWindowStartS"])
    end = min(float(out_dur), float(cfg["denseWindowEndS"]))
    dense = [row for row in rows if _interval(row)[1] > start
             and _interval(row)[0] < end]
    if end > start:
        ratio = _coverage(dense, start, end)
        minimum = float(cfg["minimumCoverageRatio"])
        if ratio + 1e-6 < minimum:
            rep.error(f"face-bridge dense-window graphic coverage {ratio:.1%} "
                      f"is below profile minimum {minimum:.1%}")
    maximum = _maximum_dense_forms(words, out_dur, selected_profile, start, end)
    for issue in _sequence_errors(dense, cfg, maximum):
        rep.error(issue)
    for issue in _zoom_errors(plan, cfg, start, end):
        rep.error(issue)
