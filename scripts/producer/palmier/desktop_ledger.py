"""Refresh stable Desktop element bindings against current Palmier track order."""
from __future__ import annotations

from palmier.desktop_state import now
from palmier.mcp_client import PalmierError


def clip_frames(clip: dict) -> tuple[int, int] | None:
    """Return one clip's half-open frame window when readback exposes it."""
    value = clip.get("frames")
    if isinstance(value, list) and len(value) == 2 \
            and all(isinstance(item, int) for item in value):
        return value[0], value[1]
    start, end = clip.get("startFrame"), clip.get("endFrame")
    return (start, end) if isinstance(start, int) and isinstance(end, int) else None


def clip_inventory(timeline: dict) -> dict[str, dict]:
    """Index readback clips by stable clip id and attach current track index."""
    result = {}
    for track_index, track in enumerate(timeline.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and isinstance(clip.get("id"), str):
                result[clip["id"]] = {**clip, "_trackIndex": track_index}
    return result


def _assert_binding(ident: str, row: dict, clip: dict) -> None:
    expected = (row.get("mediaRef"),
                (row.get("startFrame"), row.get("endFrame")))
    actual = (clip.get("mediaRef"), clip_frames(clip))
    if expected != actual:
        raise PalmierError(
            f"Desktop element {ident!r} drifted from its ledger binding")


def migrate_element_ledger(state: dict) -> dict:
    """Upgrade legacy bindings in place without changing element identity."""
    ledger = state.get("elementLedger")
    if not isinstance(ledger, dict) or ledger.get("schemaVersion") not in {1, 2}:
        raise PalmierError("incremental revision requires a current element ledger")
    elements = ledger.get("elements")
    if not isinstance(elements, dict):
        raise PalmierError("Desktop element ledger has no elements")
    for row in elements.values():
        if isinstance(row, dict):
            row.setdefault("version", 1)
            row.setdefault("generation", 1)
    ledger.update({"schemaVersion": 2,
                   "tombstones": ledger.get("tombstones") or {}})
    return ledger


def refresh_element_ledger(state: dict, timeline: dict) -> None:
    """Resolve current track indices without trusting insertion-era positions."""
    ledger = migrate_element_ledger(state)
    elements = ledger["elements"]
    clips = clip_inventory(timeline)
    for ident, row in elements.items():
        if not isinstance(row, dict) or row.get("status") != "current":
            raise PalmierError(f"Desktop element {ident!r} has an unfinished replacement")
        clip = clips.get(row.get("clipId"))
        if not isinstance(clip, dict):
            raise PalmierError(f"Desktop element {ident!r} is absent from readback")
        _assert_binding(str(ident), row, clip)
        row.update({"trackIndex": clip["_trackIndex"], "updatedAt": now()})
    ledger["updatedAt"] = now()
