#!/usr/bin/env python3
"""Fail-closed placement evidence gate plus advisory eye-trace QC."""

from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_checks import CheckResult, FAIL, PASS, WARN  # noqa: E402
from planner.eye_trace import CFG as EYE_TRACE, evaluate_rows  # noqa: E402
from producer_config import MOTION, TREATMENTS, TREATMENT_DEFAULT  # noqa: E402


def _is_produced(plan: dict) -> bool:
    """Whether this treatment enables graphics or motion."""
    treatment = (plan.get("target") or {}).get("treatment", TREATMENT_DEFAULT)
    flags = TREATMENTS.get(treatment, TREATMENTS[TREATMENT_DEFAULT])
    return bool(flags.get("motion") or flags.get("graphics"))


def _read_rows(path: str) -> tuple[list[dict] | None, str]:
    """Read and shape-check a graphics placement sidecar."""
    try:
        with open(path) as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable placement sidecar: {exc}"
    valid_shape = isinstance(value, list) and all(
        isinstance(row, dict) for row in value)
    if not valid_shape:
        return None, "placement sidecar must be a JSON array of objects"
    for row in value:
        if row.get("gazeDistFrac") is None:
            continue
        try:
            float(row["gazeDistFrac"])
            float(row["outStart"])
        except (KeyError, TypeError, ValueError):
            return None, "placement sidecar contains malformed measurements"
    return value, ""


def _valid_bbox(raw: object) -> bool:
    """Whether a placement bbox is four finite, ordered pixel coordinates."""
    if not isinstance(raw, list) or len(raw) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(value) for value in raw)
    except (TypeError, ValueError):
        return False
    return all(map(math.isfinite, (x0, y0, x1, y1))) and x1 > x0 and y1 > y0


def _canvas_dims(raw: object) -> tuple[float, float] | None:
    """Positive finite delivery dimensions from a placement row."""
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    try:
        width, height = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (width, height))) or width <= 0 or height <= 0:
        return None
    return width, height


def _fixed_edge_error(graphic: dict, row: dict) -> str | None:
    """Require registered rails to stay INSIDE their registered edge band.

    The recompose contract clears the face out of ``1 - width_frac`` of the
    canvas and assumes the rail's pixels live in the remaining edge band —
    that band is the invariant to verify, using the registry's own
    ``width_frac``/``side`` numbers. Flush-to-edge was the old expectation,
    but it only describes FIELD rails (nateherk-rail's cream field measures
    [0, 0, 633, 1079]); glass-rail's anatomy is floating glass pills with
    comp-internal margins and vertical centering, so a correct delivery
    (measured 4K: pills at [52, 750, 1214, 1496], band bound 1268) can never
    touch the canvas edges. Containment still catches every real drift: a
    rail escaping toward the cleared face region crosses the band bound.

    Explicit own-screen entries use the complete native canvas, not this
    free-band rail geometry. Their exact delivery coverage is checked below.
    """
    if graphic.get("anchor") == "own-screen":
        return None
    geometry = MOTION["recompose"]["geometry"].get(str(graphic.get("kind")))
    if not isinstance(geometry, dict):
        return None
    bbox = [float(value) for value in row["placedBBox"]]
    canvas = _canvas_dims(row.get("canvas"))
    if canvas is None:
        return "fixed-edge rail has no delivery canvas measurement"
    side = str(geometry.get("side"))
    if side == "spec":
        side = str((graphic.get("spec") or {}).get(
            "side", geometry.get("default_side", "left")))
    band = float(geometry["width_frac"]) * canvas[0]
    if side == "left":
        horizontal = max(-bbox[0], bbox[2] - band)
    else:
        horizontal = max(bbox[2] - (canvas[0] - 1), (canvas[0] - band) - bbox[0])
    vertical = max(-bbox[1], bbox[3] - (canvas[1] - 1))
    if horizontal > 2 or vertical > 2:
        return (f"fixed-edge {side} rail shifted off its registered edge band "
                f"(bbox {row['placedBBox']}, canvas {row.get('canvas')}, "
                f"band {band:.0f}px)")
    return None


def _placement_error(plan: dict, rows: list[dict]) -> str | None:
    """Validate one landed bbox per graphic and exact own-screen coverage."""
    graphics = plan.get("graphicsTrack") or []
    if len(rows) != len(graphics):
        return f"placement evidence has {len(rows)} row(s) for {len(graphics)} graphic(s)"
    for index, (graphic, row) in enumerate(zip(graphics, rows)):
        bbox = row.get("placedBBox")
        if not _valid_bbox(bbox):
            return f"graphicsTrack[{index}] has no measurable landed bbox"
        fixed_error = _fixed_edge_error(graphic, row)
        if fixed_error:
            return f"graphicsTrack[{index}] {fixed_error}"
        if graphic.get("anchor") != "own-screen":
            continue
        canvas = _canvas_dims(row.get("canvas"))
        if canvas is None or [float(value) for value in bbox] != [0.0, 0.0, *canvas]:
            return f"graphicsTrack[{index}] own-screen graphic did not cover the delivery canvas"
    return None


def _warnings(rows: list[dict]) -> list[CheckResult]:
    """Advisory distance warnings once placement evidence is usable."""
    _, violations = evaluate_rows(rows)
    return [CheckResult(
        "eye_trace", WARN,
        f"eye-trace: {row.get('kind')} at {float(row['outStart']):.1f}s lands "
        f"{float(row['gazeDistFrac']):.2f} screen units from the gaze point "
        f"(> {EYE_TRACE['warn_dist_frac']:g})",
        f"advisory (measured null baseline 0.35); flag "
        f"'{EYE_TRACE['jolt_flag_key']}': true if deliberate")
        for row in violations]


def check_eye_trace(plan: dict, out_dir: str) -> list[CheckResult]:
    """Require placement evidence, then grade eye-trace distance advisories."""
    if not _is_produced(plan) or not plan.get("graphicsTrack"):
        return []
    sidecar = os.path.join(out_dir, "graphics_placements.json")
    if not os.path.exists(sidecar):
        return [CheckResult(
            "eye_trace", FAIL, "placements sidecar missing",
            "produced graphics require graphics_placements.json")]
    rows, error = _read_rows(sidecar)
    if rows is None:
        return [CheckResult("eye_trace", FAIL, error,
                            "cannot verify produced graphic placement")]
    placement_error = _placement_error(plan, rows)
    if placement_error:
        return [CheckResult("eye_trace", FAIL, placement_error,
                            "cannot verify produced graphic placement")]
    checked = sum(row.get("gazeDistFrac") is not None for row in rows)
    if EYE_TRACE.get("audit") == "off":
        return [CheckResult(
            "eye_trace", PASS, f"{checked} measurable placement row(s)",
            "distance advisory disabled; evidence gate still enforced")]
    warnings = _warnings(rows)
    if warnings:
        return warnings
    if checked == 0:
        return [CheckResult(
            "eye_trace", PASS, f"{len(rows)} landed graphic bbox(es) verified",
            "gaze source unavailable; eye-trace distance remains advisory")]
    return [CheckResult(
        "eye_trace", PASS,
        f"{checked} gaze-measurable graphic(s) within "
        f"{EYE_TRACE['warn_dist_frac']:g} of the gaze point",
        f"{len(rows)} placement row(s) in the sidecar")]
