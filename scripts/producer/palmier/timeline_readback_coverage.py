"""Conservative coverage facts for unpaged Palmier timeline snapshots."""
from __future__ import annotations

CAPTION_DETAIL_CAP = 200


def default_timeline_coverage(timeline: dict) -> dict:
    """Flag caption groups whose compact readback may hide capped rows."""
    capped: list[dict] = []
    for track_index, track in enumerate(timeline.get("tracks", [])):
        if not isinstance(track, dict):
            continue
        for group_index, group in enumerate(track.get("captionGroups") or []):
            if not isinstance(group, dict):
                continue
            count, details = group.get("clipCount", 0), group.get("clips")
            complete = isinstance(details, list) and len(details) == count
            if isinstance(count, int) and not isinstance(count, bool) \
                    and count > CAPTION_DETAIL_CAP and not complete:
                capped.append({
                    "track": track_index, "group": group_index,
                    "clipCount": count,
                })
    return {
        "scope": "mcp-readable-timeline",
        "captionDetailRequested": True, "complete": not capped,
        "limitations": (
            ["caption groups above Palmier's 200-row detail cap"]
            if capped else []),
        "cappedCaptionGroups": capped,
    }
