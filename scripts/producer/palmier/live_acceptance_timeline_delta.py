"""Canonical non-target timeline comparison for one scoped clip repair."""
from __future__ import annotations

import copy
import json

_RUNTIME_ROOT_KEYS = {"canGenerate", "currentFrame", "timelines"}


def _without_target(timeline: dict, clip_id: str) -> dict | None:
    value = copy.deepcopy(timeline)
    for key in _RUNTIME_ROOT_KEYS:
        value.pop(key, None)
    occurrences = 0
    for track in value.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        clips = track.get("clips")
        if not isinstance(clips, list):
            continue
        kept = []
        for clip in clips:
            if isinstance(clip, dict) and clip.get("id") == clip_id:
                occurrences += 1
            else:
                kept.append(clip)
        track["clips"] = kept
    return value if occurrences == 1 else None


def canonical_non_target_equal(
        before: dict, after: dict, old_clip_id: str,
        new_clip_id: str) -> bool:
    """Compare every MCP-readable edit field after removing only the repair."""
    old = _without_target(before, old_clip_id)
    new = _without_target(after, new_clip_id)
    if old is None or new is None:
        return False
    return json.dumps(old, sort_keys=True, separators=(",", ":")) == json.dumps(
        new, sort_keys=True, separators=(",", ":"))
