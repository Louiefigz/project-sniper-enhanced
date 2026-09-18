"""Bounded absolute-range screening with original graphic orders and full cues.

This is a pure consumer of owner-held facts, not a media/source authority. V1
retains its exact full-program/contiguous-order contract in its original file.
"""
from __future__ import annotations

from cut_preview_io import digest
from guided_caption_layout import (Guard, ObservationReader, SCOPE, _MAX_PAIRS,
    _clock, _closed, _cue, _declaration, _graphic, _observation, _screen, _sha, _span)

POLICY = "native-caption-layout-screen-v2"


def _pairs(graphic: dict, cues: list[dict], coverage: tuple[int, int]) -> list[tuple]:
    """Retain full cue/animation evidence while intersecting the reported range."""
    rows = []
    for cue in cues:
        start = max(cue["startFrame"], graphic["startFrame"], coverage[0])
        end = min(cue["endFrameExclusive"], graphic["endFrameExclusive"], coverage[1])
        if start < end:
            rows.append((cue, start, end))
    return rows


def _one(graphic: dict, cues: list[dict], context: tuple) -> dict:
    """No absent/unqualified observation can become a screening success."""
    declarations, clock, coverage, reader, guard = context
    pairs = _pairs(graphic, cues, coverage)
    base = {"graphicId": graphic["graphicId"], "order": graphic["order"], "intersections": [
        {"cueId": cue["cueId"], "startFrame": start, "endFrameExclusive": end} for cue, start, end in pairs]}
    if not pairs:
        return {**base, "state": "not-applicable", "reason": "no-simultaneous-caption-in-coverage"}
    try:
        guard()
        declaration = _declaration(declarations[graphic["graphicId"]], graphic, clock)
        observed = reader(graphic["binding"], declaration)
        if observed is None:
            return {**base, "state": "unqualified", "reason": "no-owned-geometry-observation"}
        original = digest(list(observed))
        reference, roles = _observation(observed, (graphic, declaration, clock))
        rows = [{"cueId": cue["cueId"], "startFrame": start, "endFrameExclusive": end,
                 "conflicts": _screen(cue, declaration, roles)} for cue, start, end in pairs]
        guard()
        final = reader(graphic["binding"], declaration)
        if type(final) is not tuple or digest(list(final)) != original:
            raise ValueError("owned geometry changed at final covered read")
        return {**base, "intersections": rows, "observation": reference,
                "state": "envelope-conflict" if any(row["conflicts"] for row in rows) else "screened-no-overlap"}
    except (KeyError, ValueError, TypeError, OSError) as error:
        return {**base, "state": "unqualified", "reason": str(error)[:1000]}


def _inventory(value: dict, clock: dict, coverage: tuple[int, int]) -> tuple:
    """Reject reordered/duplicate original orders without renumbering a subset."""
    if any(type(value[key]) is not list for key in ("cues", "graphics", "declarations")) \
            or len(value["cues"]) > 4096 or len(value["graphics"]) > 128 \
            or len(value["declarations"]) > 128 or len(value["cues"]) * len(value["graphics"]) > _MAX_PAIRS:
        raise ValueError("covered layout exceeds bounded workload")
    cues = [_cue(row, clock) for row in value["cues"]]
    graphics = [_graphic(row, clock) for row in value["graphics"]]
    orders = [row["order"] for row in graphics]
    if orders != sorted(set(orders)) or len({row["graphicId"] for row in graphics}) != len(graphics) \
            or len({row["cueId"] for row in cues}) != len(cues):
        raise ValueError("covered layout loses unique original identity/order")
    if any(row["startFrame"] >= coverage[1] or row["endFrameExclusive"] <= coverage[0] for row in graphics):
        raise ValueError("covered graphic is outside the declared absolute range")
    declarations = {row["binding"]["graphicId"]: row for row in value["declarations"]}
    if len(declarations) != len(value["declarations"]) or set(declarations) - {row["graphicId"] for row in graphics}:
        raise ValueError("covered declarations duplicate or transplant identities")
    return cues, graphics, declarations


def inspect_covered_layout(value: dict, reader: ObservationReader, guard: Guard) -> dict:
    """Screen only explicit coverage; never relabel an opening as the full body."""
    guard()
    before = digest(value)
    _closed(value, {"schemaVersion", "kind", "clock", "coverage", "captionProjectionHash",
                    "cues", "graphics", "declarations"}, "covered layout input")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 2 \
            or value["kind"] != "held-caption-layout-input":
        raise ValueError("covered layout version differs")
    _sha(value["captionProjectionHash"])
    clock = _clock(value["clock"])
    row = _closed(value["coverage"], {"startFrame", "endFrameExclusive"}, "layout coverage")
    coverage = _span(row, clock["totalFrames"])
    cues, graphics, declarations = _inventory(value, clock, coverage)
    rows = [_one(row, cues, (declarations, clock, coverage, reader, guard)) for row in graphics]
    guard()
    if digest(value) != before:
        raise ValueError("held covered layout changed during observation")
    states = {row["state"] for row in rows}
    state = next((item for item in ("unqualified", "envelope-conflict", "screened-no-overlap")
                  if item in states), "not-applicable")
    return {"schemaVersion": 2, "policy": POLICY, "scope": SCOPE, "state": state,
        "clock": clock, "coverage": row, "captionProjectionHash": value["captionProjectionHash"],
        "inputHash": before, "graphics": rows, "qcPassed": False,
        "creativeApproved": False, "deliveryApproved": False}
