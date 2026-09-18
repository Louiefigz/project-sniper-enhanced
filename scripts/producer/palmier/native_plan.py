"""Deterministic validation for Palmier-native surgical mutation plans."""
from __future__ import annotations

import copy
import re
from typing import Any

from palmier.mcp_client import PalmierError

MAX_OPERATIONS = 24
_SHA = re.compile(r"^[0-9a-f]{64}$")
_LANES = {"cuts", "graphics", "motion", "captions", "audio", "color",
          "effects", "reframe"}
ALLOWED_TOOLS = {
    "remove_silence", "remove_words", "ripple_delete_ranges", "split_clips",
    "set_clip_properties", "set_keyframes", "apply_layout", "add_texts",
    "update_text", "add_captions", "apply_color", "apply_effect",
    "denoise_audio",
}
MAY_REMOVE = {"remove_silence", "remove_words", "ripple_delete_ranges",
              "split_clips"}
MAY_ADD = {"split_clips", "add_texts", "add_captions"}
_TOOL_LANES = {
    "remove_silence": {"cuts"}, "remove_words": {"cuts"},
    "ripple_delete_ranges": {"cuts"}, "split_clips": {"cuts"},
    "apply_layout": {"reframe"},
    "add_texts": {"graphics"}, "update_text": {"graphics", "captions"},
    "add_captions": {"captions"}, "apply_color": {"color"},
    "apply_effect": {"effects"}, "denoise_audio": {"audio"},
}
_KEYS = {
    "remove_silence": set(),
    "remove_words": {"words", "matches", "cutAggressiveness", "language"},
    "ripple_delete_ranges": {"clipId", "trackIndex", "ranges", "units",
                             "ignoreSyncLockedTracks"},
    "split_clips": {"splits", "trackIndex", "frames"},
    "set_clip_properties": {"clipIds", "durationFrames", "trimStartFrame",
                            "trimEndFrame", "speed", "volume", "opacity",
                            "transform", "blendMode"},
    "set_keyframes": {"clipId", "property", "keyframes"},
    "apply_layout": {"layout", "slots", "fit", "startFrame", "endFrame"},
    "add_texts": {"entries"},
    "update_text": {"clipIds", "captionGroupId", "content", "fontName",
                    "fontSize", "color", "borderColor", "backgroundColor",
                    "highlightColor", "isBold", "isItalic", "alignment",
                    "animation", "transform"},
    "add_captions": {"language", "maxWords", "textCase", "fontName",
                     "fontSize", "color", "borderColor", "backgroundColor",
                     "highlightColor", "isBold", "isItalic", "alignment",
                     "animation", "transform", "censorProfanity"},
    "apply_color": {"clipIds", "reset", "exposure", "contrast", "highlights",
                    "shadows", "whites", "blacks", "temperature", "tint",
                    "saturation", "vibrance", "shadowsHue", "shadowsAmount",
                    "shadowsLum", "midsHue", "midsAmount", "midsGamma",
                    "highlightsHue", "highlightsAmount", "highlightsLum",
                    "masterCurve", "redCurve", "greenCurve", "blueCurve",
                    "hueCurves"},
    "apply_effect": {"clipIds", "effects", "remove"},
    "denoise_audio": {"clipIds", "enabled", "strength"},
}
_REQUIRED = {
    "remove_silence": set(), "remove_words": set(),
    "ripple_delete_ranges": {"ranges", "units"},
    "split_clips": set(), "set_clip_properties": {"clipIds"},
    "set_keyframes": {"clipId", "property", "keyframes"},
    "apply_layout": {"layout", "slots"}, "add_texts": {"entries"},
    "update_text": set(), "add_captions": set(),
    "apply_color": {"clipIds"}, "apply_effect": {"clipIds"},
    "denoise_audio": {"clipIds"},
}


def _timeline_ids(timeline: dict) -> tuple[set[str], set[str], set[int]]:
    clips: set[str] = set()
    groups: set[str] = set()
    tracks: set[int] = set()
    for index, track in enumerate(timeline.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        tracks.add(index)
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            if isinstance(clip.get("id"), str):
                clips.add(clip["id"])
            audio = clip.get("audio")
            if isinstance(audio, dict) and isinstance(audio.get("id"), str):
                clips.add(audio["id"])
        for group in track.get("captionGroups") or []:
            if isinstance(group, dict) and isinstance(group.get("captionGroupId"), str):
                groups.add(group["captionGroupId"])
    return clips, groups, tracks


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value \
            or any(not isinstance(item, str) or not item for item in value):
        raise PalmierError(f"Palmier native plan {label} must be non-empty strings")
    return value


def _validate_ids(tool: str, args: dict, timeline: dict) -> None:
    clips, groups, tracks = _timeline_ids(timeline)
    ids: list[str] = []
    if "clipId" in args:
        ids.append(args["clipId"])
    if "clipIds" in args:
        ids.extend(_strings(args["clipIds"], f"{tool}.clipIds"))
    for row in args.get("splits") or []:
        if isinstance(row, dict):
            ids.append(row.get("clipId"))
    for slot in args.get("slots") or []:
        if not isinstance(slot, dict) or "mediaRef" in slot:
            raise PalmierError("native apply_layout may re-layout existing clips only")
        ids.extend(_strings(slot.get("clipIds"), "apply_layout slots.clipIds"))
    if any(not isinstance(item, str) or item not in clips for item in ids):
        raise PalmierError(f"Palmier native plan {tool} references an unknown clip id")
    group = args.get("captionGroupId")
    if group is not None and group not in groups:
        raise PalmierError("Palmier native plan references an unknown caption group")
    for key in ("trackIndex",):
        if key in args and (isinstance(args[key], bool) or args[key] not in tracks):
            raise PalmierError(f"Palmier native plan {tool}.{key} is not a current track")


def _validate_frames(tool: str, args: dict, timeline: dict) -> None:
    total = timeline.get("totalFrames")
    if not isinstance(total, int) or total < 1:
        raise PalmierError("Palmier native plan requires a positive timeline duration")
    frames: list[object] = []
    frames.extend(args.get("frames") or [])
    frames.extend(args[key] for key in (
        "durationFrames", "trimStartFrame", "trimEndFrame",
        "startFrame", "endFrame") if key in args)
    for row in args.get("keyframes") or []:
        if isinstance(row, list) and row:
            frames.append(row[0])
    for row in args.get("splits") or []:
        if isinstance(row, dict):
            frames.append(row.get("atFrame"))
    for row in args.get("entries") or []:
        if not isinstance(row, dict):
            raise PalmierError(f"Palmier native plan {tool}.entries is malformed")
        frames.extend((row.get("startFrame"), row.get("endFrame")))
    for pair in args.get("ranges") or []:
        if not isinstance(pair, list) or len(pair) != 2:
            raise PalmierError(f"Palmier native plan {tool}.ranges is malformed")
        if _number(pair[0]) and _number(pair[1]) and pair[1] <= pair[0]:
            raise PalmierError(f"Palmier native plan {tool}.ranges is unordered")
        frames.extend(pair)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or value < 0 or value > total for value in frames if value is not None):
        raise PalmierError(f"Palmier native plan {tool} has an out-of-range frame")


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _property_lanes(args: dict) -> set[str]:
    lanes: set[str] = set()
    keys = set(args) - {"clipIds"}
    if keys & {"durationFrames", "trimStartFrame", "trimEndFrame", "speed"}:
        lanes.add("cuts")
    if "volume" in keys:
        lanes.add("audio")
    if keys & {"opacity", "blendMode"}:
        lanes.add("graphics")
    if "transform" in keys:
        lanes.add("reframe")
    return lanes


def _operation_lanes(tool: str, args: dict) -> set[str]:
    if tool == "set_clip_properties":
        return _property_lanes(args)
    if tool == "set_keyframes":
        return {"audio"} if args.get("property") == "volume" else {"motion"}
    return _TOOL_LANES[tool]


def _validate_collections(tool: str, args: dict) -> None:
    if tool == "remove_words":
        _strings(args.get("words") or args.get("matches"), f"{tool}.selection")
    if tool == "split_clips" and args.get("splits"):
        rows = args["splits"]
        if not isinstance(rows, list) or any(not isinstance(row, dict)
                or set(row) != {"clipId", "atFrame"} for row in rows):
            raise PalmierError("split_clips.splits must be clipId/atFrame rows")
    if tool == "set_keyframes":
        rows = args.get("keyframes")
        if not isinstance(rows, list) or not rows or any(
                not isinstance(row, list) or len(row) != 2
                or not _number(row[0]) for row in rows):
            raise PalmierError("set_keyframes.keyframes must be [frame, value] rows")
    if tool == "add_texts":
        rows = args.get("entries")
        if not isinstance(rows, list) or not rows or any(
                not isinstance(row, dict) or not isinstance(row.get("content"), str)
                or not row["content"].strip() or not _number(row.get("startFrame"))
                or not _number(row.get("endFrame"))
                or row["endFrame"] <= row["startFrame"] for row in rows):
            raise PalmierError("add_texts.entries require content and ordered frames")


def _validate_shape(tool: str, args: dict) -> None:
    if not _REQUIRED[tool] <= set(args):
        raise PalmierError(f"Palmier native operation {tool} is missing required arguments")
    if tool == "remove_words" and bool(args.get("words")) == bool(args.get("matches")):
        raise PalmierError("remove_words requires exactly one of words or matches")
    if tool == "ripple_delete_ranges":
        if args.get("units") != "frames" \
                or bool("clipId" in args) == bool("trackIndex" in args):
            raise PalmierError("native ripple deletion requires frame units and one target")
    if tool == "split_clips" and bool(args.get("splits")) == bool(args.get("frames")):
        raise PalmierError("split_clips requires explicit splits or track frames")
    if tool == "set_clip_properties":
        changed = set(args) - {"clipIds"}
        if not changed:
            raise PalmierError("set_clip_properties changes no property")
        for key in ("volume", "opacity"):
            if key in args and (not _number(args[key])
                                or not 0 <= args[key] <= 1):
                raise PalmierError(f"set_clip_properties.{key} must be 0-1")
        if "speed" in args and (not _number(args["speed"])
                                or args["speed"] <= 0):
            raise PalmierError("set_clip_properties.speed must be positive")
    if tool == "set_keyframes" and args.get("property") not in {
            "volume", "opacity", "rotation", "position", "scale", "crop"}:
        raise PalmierError("set_keyframes.property is unsupported")
    if tool == "update_text" and not args.get("clipIds") \
            and not args.get("captionGroupId"):
        raise PalmierError("update_text requires clipIds or captionGroupId")
    if tool == "denoise_audio" and "strength" in args \
            and (not _number(args["strength"])
                 or not 0 <= args["strength"] <= 1):
        raise PalmierError("denoise_audio.strength must be 0-1")
    _validate_collections(tool, args)


def validate_native_plan(value: object, authority: dict) -> dict:
    """Return a defensive copy after validating scope, ids, and frame bounds."""
    top_keys = {"schemaVersion", "parent", "requestHash", "lanes", "operations"}
    if not isinstance(value, dict) or set(value) != top_keys \
            or value.get("schemaVersion") != 1:
        raise PalmierError("Palmier native plan must be schemaVersion 1")
    if not isinstance(value.get("requestHash"), str) \
            or not _SHA.fullmatch(value["requestHash"]):
        raise PalmierError("Palmier native plan requestHash is invalid")
    lanes = value.get("lanes")
    if not isinstance(lanes, list) or not lanes or len(lanes) > len(_LANES) \
            or any(not isinstance(lane, str) or lane not in _LANES
                   for lane in lanes) or len(set(lanes)) != len(lanes):
        raise PalmierError("Palmier native plan lanes must be unique supported lanes")
    parent = value.get("parent")
    expected = {key: authority.get(key) for key in
                ("projectId", "timelineId", "fingerprint")}
    if parent != expected:
        raise PalmierError("Palmier native plan parent authority is stale")
    operations = value.get("operations")
    if not isinstance(operations, list) or not operations \
            or len(operations) > MAX_OPERATIONS:
        raise PalmierError(f"Palmier native plan requires 1-{MAX_OPERATIONS} operations")
    timeline = authority.get("timeline")
    if not isinstance(timeline, dict):
        raise PalmierError("Palmier native authority has no complete timeline")
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or set(operation) != {"tool", "args", "reason"}:
            raise PalmierError(f"Palmier native operation {index + 1} has an invalid envelope")
        tool, args, reason = operation["tool"], operation["args"], operation["reason"]
        if tool not in ALLOWED_TOOLS or not isinstance(args, dict):
            raise PalmierError(f"Palmier native operation {index + 1} uses a forbidden tool")
        if set(args) - _KEYS[tool]:
            raise PalmierError(f"Palmier native operation {tool} has unknown arguments")
        if not isinstance(reason, str) or not reason.strip():
            raise PalmierError(f"Palmier native operation {tool} has no editorial reason")
        if not _operation_lanes(tool, args) & set(lanes):
            raise PalmierError(
                f"Palmier native operation {tool} is outside the declared lanes")
        _validate_shape(tool, args)
        _validate_ids(tool, args, timeline)
        _validate_frames(tool, args, timeline)
    return copy.deepcopy(value)


def remap_plan_ids(plan: dict, identities: dict[str, str]) -> dict:
    """Translate parent clip/group ids to regenerated candidate ids."""
    def visit(value: Any, key: str | None = None) -> Any:
        if isinstance(value, list):
            return [visit(item, key) for item in value]
        if isinstance(value, dict):
            return {name: visit(item, name) for name, item in value.items()}
        if isinstance(value, str) and key in {"clipId", "clipIds", "captionGroupId"}:
            return identities.get(value, value)
        return value
    return visit(plan)
