"""Bind and prove Desktop Palmier keyframe mutations."""
from __future__ import annotations

import copy
import json

from palmier.desktop_ledger import clip_inventory
from palmier.desktop_state import read_record
from palmier.keyframe_readback import compare_keyframe_rows, keyframe_map
from palmier.mcp_client import PalmierError


def _steps(state: dict) -> list[dict]:
    value = read_record(state["operations"]["path"], "operation manifest")
    return [row for row in value.get("steps") or []
            if isinstance(row, dict) and row.get("op") == "keyframes"]


def _video_clips(timeline: dict) -> list[dict]:
    clips = []
    for track in timeline.get("tracks") or []:
        if not isinstance(track, dict) or "audio" in str(
                track.get("type", track.get("trackType", ""))).lower():
            continue
        clips.extend(clip for clip in track.get("clips") or []
                     if isinstance(clip, dict)
                     and clip.get("mediaType") != "audio")
    return sorted(
        clips, key=lambda row: (
            (row.get("frames") or [0])[0], str(row.get("id"))))


def bind_keyframe_operation(
        tool: str, args: dict, state: dict,
        timeline: dict | None) -> dict | None:
    """Bind exact clip/property/rows to one unconsumed worklist step."""
    if tool != "set_keyframes" or not isinstance(timeline, dict):
        return None
    clips = _video_clips(timeline)
    verified = set(state.get("verifiedMotionKeys") or [])
    matches = []
    for index, row in enumerate(_steps(state)):
        clip_index = row.get("clip")
        if not isinstance(clip_index, int) or clip_index >= len(clips):
            continue
        expected = {
            "clipId": clips[clip_index].get("id"),
            "property": row.get("property"), "keyframes": row.get("rows")}
        key = json.dumps([index, expected], sort_keys=True)
        if args == expected and key not in verified:
            matches.append((index, row, key))
    if len(matches) != 1:
        raise PalmierError(
            "Palmier keyframes are not a unique bound worklist mutation")
    index, row, key = matches[0]
    return {
        "kind": "keyframes", "stepIndex": index, "key": key,
        "clipId": args["clipId"], "property": row["property"],
        "rows": row["rows"],
    }


def _without_keyframes(value: dict) -> dict:
    result = copy.deepcopy(value)
    result.pop("keyframes", None)
    return result


def observe_keyframe_operation(observation: object) -> bool:
    """Require only the bound keyframe property to change."""
    binding = observation.pending.get("binding")
    if not isinstance(binding, dict) or binding.get("kind") != "keyframes":
        return False
    old = clip_inventory(observation.before)
    new = clip_inventory(observation.after)
    clip_id = binding["clipId"]
    if set(old) != set(new) or clip_id not in new:
        raise PalmierError("keyframe mutation changed clip identities")
    if any(_without_keyframes(old[key]) != _without_keyframes(new[key])
           for key in old):
        raise PalmierError("keyframe mutation changed non-keyframe clip state")
    found = keyframe_map(new[clip_id])
    if not isinstance(found, dict) or binding["property"] not in found:
        raise PalmierError("keyframe readback omitted the bound property")
    evidence = compare_keyframe_rows(
        found[binding["property"]], binding["rows"]).as_dict()
    observation.state.setdefault("verifiedMotionKeys", []).append(
        binding["key"])
    observation.state.setdefault("motionLedger", []).append({
        "clipId": clip_id, "property": binding["property"],
        "rows": binding["rows"], "readback": evidence,
    })
    return True


def require_motion_ready(state: dict) -> dict | None:
    """Require a verified readback for every authored keyframe operation."""
    expected = _steps(state)
    if not expected:
        return None
    found = state.get("motionLedger") or []
    if len(found) != len(expected):
        raise PalmierError("Desktop keyframe readback is incomplete")
    return {"status": "verified", "properties": len(found),
            "readback": [row["readback"] for row in found]}
