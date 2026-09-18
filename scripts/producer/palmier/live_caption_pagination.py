"""Connected proof for Palmier caption groups above its 200-row detail cap."""
from __future__ import annotations

import time
from typing import Any

from palmier.mcp_client import PalmierError
from palmier.timeline_readback import (
    CompleteTimelineReadback, read_complete_timeline)
from palmier.timeline_readback_coverage import CAPTION_DETAIL_CAP

_TRANSIENT = (
    "changed during", "incomplete", "omitted requested caption detail",
)


def caption_signature(timeline: object) -> tuple[tuple[int, str, int], ...]:
    """Return compact caption-group identities and declared row counts."""
    if not isinstance(timeline, dict):
        raise PalmierError("caption pagination compact read is malformed")
    rows = []
    for track_index, track in enumerate(timeline.get("tracks") or []):
        if not isinstance(track, dict):
            raise PalmierError("caption pagination track is malformed")
        for group in track.get("captionGroups") or []:
            if not isinstance(group, dict):
                raise PalmierError("caption pagination group is malformed")
            ident, count = group.get("captionGroupId"), group.get("clipCount")
            valid = (
                isinstance(ident, str) and bool(ident)
                and isinstance(count, int) and not isinstance(count, bool)
                and count >= 0
            )
            if not valid:
                raise PalmierError(
                    "caption pagination group has no stable count identity")
            rows.append((track_index, ident, count))
    return tuple(rows)


def _coverage_proof(found: CompleteTimelineReadback) -> dict:
    coverage = found.coverage
    groups = coverage.get("captionGroups")
    capped = [
        row for row in groups or []
        if isinstance(row, dict)
        and row.get("expectedClipCount", 0) > CAPTION_DETAIL_CAP
    ]
    exact = bool(capped) and all(
        row.get("readClipCount") == row.get("expectedClipCount")
        for row in capped)
    valid = (
        coverage.get("complete") is True
        and coverage.get("captionDetailRequested") is True
        and coverage.get("strategy") == "bounded-frame-windows"
        and coverage.get("windowCount", 0) > 1
        and coverage.get("closingCompactRead") is True
        and exact
    )
    if not valid:
        raise PalmierError(
            "connected caption pagination did not prove a complete capped group")
    return {
        "kind": "connected-native-caption-pagination",
        "timelineId": found.timeline.get("id"),
        "totalFrames": found.timeline.get("totalFrames"),
        "coverage": coverage,
        "cappedGroupCount": len(capped),
        "maximumCaptionCount": max(
            row["expectedClipCount"] for row in capped),
        "exactCounts": True,
    }


def await_capped_caption_readback(
        client: Any, deadline: Any) -> dict:
    """Wait for stable native captions, then exercise real bounded paging."""
    previous: tuple[tuple[int, str, int], ...] | None = None
    stable_reads = 0
    while True:
        compact = client.call_json("get_timeline", {})
        signature = caption_signature(compact)
        capped = any(count > CAPTION_DETAIL_CAP
                     for _track, _ident, count in signature)
        stable_reads = stable_reads + 1 \
            if capped and signature == previous else int(capped)
        previous = signature
        if stable_reads >= 2:
            try:
                found = read_complete_timeline(client)
            except PalmierError as exc:
                if not any(token in str(exc) for token in _TRANSIENT):
                    raise
                stable_reads = 0
            else:
                closing = caption_signature(
                    client.call_json("get_timeline", {}))
                if closing == caption_signature(found.timeline):
                    return {
                        **_coverage_proof(found),
                        "postReadCompactStable": True,
                    }
                stable_reads = 0
                previous = closing
        time.sleep(min(1.0, deadline.remaining()))
