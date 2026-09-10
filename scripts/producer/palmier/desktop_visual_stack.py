"""Prove final Palmier video-track order matches production composition."""
from __future__ import annotations

from palmier.desktop_ledger import clip_inventory
from palmier.mcp_client import PalmierError

_LANES = (
    "captions-alpha", "graphics", "title-cards-alpha", "broll",
)


def _visual_clip_ids(timeline: dict) -> set[str]:
    result = set()
    for track in timeline.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        kind = str(track.get("type", track.get("trackType", ""))).lower()
        if "audio" in kind:
            continue
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict) or not isinstance(clip.get("id"), str):
                continue
            if str(clip.get("mediaType", "video")).lower() != "audio":
                result.add(clip["id"])
    return result


def _lane_tracks(state: dict, clips: dict) -> tuple[dict, set[str]]:
    result = {lane: [] for lane in _LANES}
    governed = set()
    elements = (state.get("elementLedger") or {}).get("elements") or {}
    for row in elements.values():
        if not isinstance(row, dict) or row.get("status") != "current":
            continue
        ident, lane = row.get("clipId"), row.get("lane")
        if isinstance(ident, str):
            governed.add(ident)
        clip = clips.get(ident)
        if lane in result and isinstance(clip, dict):
            result[lane].append(clip["_trackIndex"])
    return result, governed


def _base_tracks(state: dict, timeline: dict, governed: set[str]) -> list[int]:
    clips = clip_inventory(timeline)
    excluded = set(governed)
    reference = state.get("exactMasterReference")
    if isinstance(reference, dict) and isinstance(reference.get("clipId"), str):
        excluded.add(reference["clipId"])
    visual = _visual_clip_ids(timeline)
    return [clips[ident]["_trackIndex"] for ident in sorted(visual - excluded)
            if ident in clips]


def require_visual_stack(state: dict, timeline: dict) -> dict:
    """Require base < b-roll < titles < graphics < captions in z-order."""
    if not isinstance(timeline, dict):
        raise PalmierError("visual stack requires current timeline readback")
    clips = clip_inventory(timeline)
    lanes, governed = _lane_tracks(state, clips)
    base = _base_tracks(state, timeline, governed)
    if not base:
        raise PalmierError("visual stack has no observable editable base")
    groups = [
        ("captions", lanes["captions-alpha"]),
        ("graphics", lanes["graphics"]),
        ("titles", lanes["title-cards-alpha"]),
        ("broll", lanes["broll"]),
        ("base", base),
    ]
    populated = [(name, rows) for name, rows in groups if rows]
    safe = all(max(upper) < min(lower)
               for (_name, upper), (_next, lower)
               in zip(populated, populated[1:]))
    if not safe:
        raise PalmierError(
            "Palmier visual track order differs from production z-order")
    return {
        "orderBottomToTop": [
            name for name, rows in reversed(populated) if rows],
        "tracks": {name: sorted(rows) for name, rows in populated},
        "proved": True,
    }
