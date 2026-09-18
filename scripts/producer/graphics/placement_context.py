#!/usr/bin/env python3
"""Materialize plan-level face geometry onto render-time graphic entries.

The graphics stage receives only ``graphicsTrack`` rows, while a plan may
legitimately carry one global ``faceBBoxNorm``.  Automatic placement must see
the same face authority without mutating the reviewed plan.
"""

from __future__ import annotations

from planner.graphics_anchors import FACE_ANCHORS, valid_face_bbox

FACE_AWARE_ANCHORS = (*FACE_ANCHORS, "free-band")


def is_face_aware(entry: dict) -> bool:
    """Whether an unpinned entry belongs to automatic face avoidance."""
    anchor = entry.get("anchor", "free-band")
    return (
        entry.get("placement") is None
        and (
            anchor in FACE_ANCHORS
            or (anchor == "free-band"
                and valid_face_bbox(entry.get("faceBBoxNorm")))
        )
    )


def bind_plan_face_bbox(track: list[dict], plan: dict) -> list[dict]:
    """Return track rows with the global face box inherited where applicable.

    Entry-level geometry wins. Explicit operator placements remain untouched.
    A present malformed global box fails closed; an absent box preserves the
    legacy authored-position path for footage without a face.
    """
    global_bbox = plan.get("faceBBoxNorm")
    if not track:
        return track
    if global_bbox is not None and not valid_face_bbox(global_bbox):
        raise ValueError(
            "plan.faceBBoxNorm must be a positive in-bounds normalized box")
    result: list[dict] = []
    for entry in track:
        anchor = entry.get("anchor", "free-band")
        eligible = (anchor in FACE_AWARE_ANCHORS
                    and entry.get("placement") is None)
        entry_bbox = entry.get("faceBBoxNorm")
        if not eligible or valid_face_bbox(entry_bbox):
            result.append(entry)
            continue
        if global_bbox is not None:
            result.append({**entry, "faceBBoxNorm": list(global_bbox)})
            continue
        if entry_bbox is not None:
            raise ValueError(
                "graphicsTrack faceBBoxNorm must be a positive in-bounds "
                "normalized box")
        result.append(entry)
    return result
