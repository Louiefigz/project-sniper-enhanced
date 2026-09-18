"""Strict current-timeline proof for governed full-canvas alpha clips."""
from __future__ import annotations

from dataclasses import dataclass

from palmier.desktop_ledger import clip_frames, clip_inventory
from palmier.mcp_client import PalmierError


@dataclass(frozen=True)
class AlphaTrackPolicy:
    """Track topology required by one alpha-asset lane."""

    label: str
    shared_track: bool
    descending_plan_order: bool = True


def _media_ref(state: dict, row: dict) -> str | None:
    media = (state.get("mediaLedger") or {}).get(row.get("assetHash"))
    return media.get("mediaRef") if isinstance(media, dict) else None


def _record_matches(
        state: dict, row: dict, record: object, clip: object) -> bool:
    if not isinstance(record, dict) or not isinstance(clip, dict):
        return False
    expected_ref = _media_ref(state, row)
    expected_window = (row.get("startFrame"), row.get("endFrame"))
    return (
        record.get("status") == "current"
        and record.get("lane") == row.get("lane")
        and record.get("assetHash") == row.get("assetHash")
        and record.get("assetPath") == row.get("assetPath")
        and record.get("mediaRef") == expected_ref
        and clip.get("mediaRef") == expected_ref
        and (record.get("startFrame"), record.get("endFrame"))
        == expected_window
        and clip_frames(clip) == expected_window
        and record.get("transform") == row.get("transform")
        and clip.get("transform") == row.get("transform")
    )


def require_alpha_records(
        state: dict, rows: list[dict], timeline: dict | None,
        policy: AlphaTrackPolicy) -> list[int]:
    """Require every ledger binding to exist and match current readback."""
    if not isinstance(timeline, dict):
        raise PalmierError(f"{policy.label} requires current timeline readback")
    clips = clip_inventory(timeline)
    elements = (state.get("elementLedger") or {}).get("elements") or {}
    records = [elements.get(row.get("elementId")) for row in rows]
    clip_ids = [record.get("clipId") if isinstance(record, dict) else None
                for record in records]
    if any(not isinstance(ident, str) for ident in clip_ids) \
            or len(set(clip_ids)) != len(rows):
        raise PalmierError(f"{policy.label} clip identities are incomplete")
    live = [clips.get(ident) for ident in clip_ids]
    if not all(_record_matches(state, row, record, clip)
               for row, record, clip in zip(
                   rows, records, live, strict=True)):
        raise PalmierError(f"{policy.label} current clip readback is incomplete")
    tracks = [clip["_trackIndex"] for clip in live]
    topology = len(set(tracks)) == (1 if policy.shared_track else len(rows))
    ordering = not policy.descending_plan_order \
        or tracks == sorted(tracks, reverse=True)
    if not topology or not ordering:
        raise PalmierError(f"{policy.label} track topology is incomplete")
    for record, clip in zip(records, live, strict=True):
        record["trackIndex"] = clip["_trackIndex"]
    return tracks
